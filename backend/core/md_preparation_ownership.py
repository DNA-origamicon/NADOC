"""One preparation controller per job across API processes and reloads."""
from functools import wraps

from backend.core import simulation_runtime as runtime


def preparation_owned(job, workspace):
    return runtime.is_owned(job.job_dir(workspace) / '.preparation')


def own_native_preparation(function):
    @wraps(function)
    async def run(*args, **kwargs):
        from backend.api.routes_md import _workspace
        from backend.core.md_job import MdJob
        job = MdJob.load(kwargs['job_id'], _workspace())
        lease = runtime.claim(job.job_dir(_workspace()) / '.preparation')
        if lease is None:
            return
        try:
            return await function(*args, **kwargs)
        finally:
            lease.close()
    return run


async def recover_owned(function, job, workspace, state):
    lease = runtime.claim(job.job_dir(workspace) / '.preparation')
    if lease is None:
        return
    try:
        return await function(job, workspace, state)
    finally:
        lease.close()
