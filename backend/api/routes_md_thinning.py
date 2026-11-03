"""Explicit preview/confirmation API for destructive NAMD trajectory thinning."""
import fcntl
import struct
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StrictInt
from starlette.concurrency import run_in_threadpool

from backend.core import trajectory_thinning as thinning
from backend.core.dcd_fast import UnsupportedDCD

router = APIRouter(tags=['md'])


class ThinJobRequest(BaseModel):
    stride: StrictInt
    fingerprint: str
    confirmed: bool = False


def _ready(job_id):
    from backend.api.routes_md import _load_job, is_running, is_active_preparation
    from backend.core import job_archive
    job = _load_job(job_id)
    if (job.status.value != 'completed' or is_running(job_id) or
            is_active_preparation(job_id) or job_archive.is_running('md_jobs', job_id)):
        raise HTTPException(409, 'Only completed jobs with local files can be thinned. Wait for transfers or simulation work to finish.')
    return job


@contextmanager
def _job_files(job_id):
    from backend.api.routes_md import _workspace, _md_segment_dcds
    job = _ready(job_id); ws = _workspace(); job_dir = job.job_dir(ws)
    if not job_dir.is_dir():
        raise HTTPException(409, 'Job storage is unavailable. Mount or transfer the job first.')
    with (job_dir/'.trajectory-thinning.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HTTPException(409, 'A thinning operation is already in progress for this job.') from exc
        try:
            thinning.recover(job_dir)
            pkg = job.package_dir(ws); sources = []
            for name, _stage, path in _md_segment_dcds(job):
                conf = pkg/(name+'.conf')
                directives = {}
                if conf.exists():
                    for line in conf.read_text().splitlines():
                        words = line.split()
                        if len(words) > 1 and not words[0].startswith('#'):
                            directives[words[0].lower()] = words[1].strip('"{}')
                topology = pkg/directives.get('structure', job.name_stem+'.psf')
                if not topology.is_file():
                    raise ValueError('Matching topology is unavailable for this job.')
                sources.append({'path': path, 'topology': topology,
                                'wrapped': directives.get('wrapall', 'off').lower() in ('on', 'yes', 'true')})
            if not sources:
                raise ValueError('No local trajectory files are available for this job.')
            yield job_dir, sources
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _run(job_id, body=None):
    try:
        with _job_files(job_id) as (job_dir, sources):
            if body is None:
                return thinning.preview(sources)
            if body.confirmed is not True:
                raise HTTPException(400, 'Explicit confirmation is required before deleting frames.')
            result = thinning.apply(sources, body.stride, body.fingerprint, job_dir,
                                    check_ready=lambda: _ready(job_id))
            from backend.core.design_disk_usage import invalidate_dir_size
            invalidate_dir_size(job_dir)
            return result
    except (ValueError, OSError, UnsupportedDCD, struct.error, IndexError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/md/jobs/{job_id}/thin/preview')
async def preview_thin_job(job_id: str):
    return await run_in_threadpool(_run, job_id)


@router.post('/md/jobs/{job_id}/thin')
async def apply_thin_job(job_id: str, body: ThinJobRequest):
    return await run_in_threadpool(_run, job_id, body)
