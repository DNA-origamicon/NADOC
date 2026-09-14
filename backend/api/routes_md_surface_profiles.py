"""Surface ion metrics, persisted per job and refreshable during dynamics."""
import json
import struct
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.core.dcd_fast import UnsupportedDCD
from backend.core.namd_surface_profiles import analyze_surface_package, persist_profile

router=APIRouter(tags=['md-metrics'])


class SurfaceProfileRequest(BaseModel):
    bins: int = Field(48, ge=12, le=200)
    max_frames: int = Field(256, ge=8, le=2048)
    discard_fraction: float = Field(.5, ge=0, lt=1, allow_inf_nan=False)
    fit_min_nm: float = Field(.6, ge=0, allow_inf_nan=False)
    fit_max_nm: float = Field(2., gt=0, allow_inf_nan=False)
    dielectric: float = Field(78.4, gt=0, le=200, allow_inf_nan=False)


def generate(job_id, options):
    from backend.api.routes_md import _load_job, _workspace, _md_segment_dcds
    job=_load_job(job_id); ws=_workspace()
    try:
        result=analyze_surface_package(job.package_dir(ws), job.name_stem, _md_segment_dcds(job), **options)
    except (ValueError, FileNotFoundError, UnsupportedDCD, IndexError, struct.error) as exc:
        raise HTTPException(409, str(exc)) from exc
    result.update(job_id=job_id,generated_at=datetime.now(timezone.utc).isoformat(),job_status=job.status.value)
    persist_profile(job.job_dir(ws)/'surface_profiles.json',result)
    return result


@router.post('/md/jobs/{job_id}/surface-profiles')
async def compute_surface_profiles(job_id: str, body: SurfaceProfileRequest):
    return await run_in_threadpool(generate,job_id,body.model_dump())


@router.get('/md/jobs/{job_id}/surface-profiles')
def saved_surface_profiles(job_id: str):
    from backend.api.routes_md import _load_job, _workspace
    job=_load_job(job_id);path=job.job_dir(_workspace())/'surface_profiles.json'
    if not path.exists(): raise HTTPException(404,'Generate surface profiles first.')
    return json.loads(path.read_text())
