"""Stop must win over preparation and an in-flight RunPod availability lookup."""

import asyncio
import shutil
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api import routes_md, routes_runpod
from backend.core import runpod_preflight, runpod_supervisor
from backend.core.md_job import MdJob, MdStatus, new_job
from backend.core.md_prep_progress import PrepTracker, build_prep_phases
from backend.core.models import Design


@pytest.mark.parametrize('delete', [False, True])
def test_stop_during_preflight_never_launches(tmp_path, monkeypatch, delete):
    monkeypatch.setattr(routes_md, '_workspace', lambda: tmp_path)
    job = new_job('cancel-race', 'equilibrium_aware_namd', '', '')
    job.execution_target = 'runpod'
    job.save(tmp_path)
    monkeypatch.setattr(routes_runpod, '_SESSION', SimpleNamespace(
        is_connected=lambda: True, api_key='test', network_volume_id='vol',
    ))
    monkeypatch.setattr(runpod_supervisor, 'n_atoms_for', lambda *_a: 10)
    monkeypatch.setattr(runpod_preflight, 'evaluate', lambda **_kw: SimpleNamespace(ok=True))
    monkeypatch.setattr(routes_md, '_runpod_client_keys', lambda: ['test'])

    async def stock(_key):
        # Simulate the Stop/Delete request arriving during the awaited lookup.
        stopped = MdJob.load(job.job_id, tmp_path)
        stopped.user_stopped = True
        stopped.status = MdStatus.stopped
        stopped.save(tmp_path)
        if delete:
            shutil.rmtree(stopped.job_dir(tmp_path))
        return {}

    monkeypatch.setattr(runpod_preflight, 'fetch_gpu_stock', stock)
    monkeypatch.setattr(runpod_supervisor, 'start_job', lambda *_a, **_kw: pytest.fail('launched after Stop'))
    if delete:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(routes_md._start_runpod_job(job))
        assert exc.value.status_code == 409
        assert not job.job_dir(tmp_path).exists()
    else:
        result = asyncio.run(routes_md._start_runpod_job(job))
        assert result['status'] == 'stopped'
        assert MdJob.load(job.job_id, tmp_path).user_stopped


def test_stop_during_preparation_prevents_autostart(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_md, '_workspace', lambda: tmp_path)
    monkeypatch.setattr(routes_md, '_sequenced_base_count', lambda _design: 1)
    body = routes_md.CreateJobRequest(autostart=True, execution_target='runpod', seed=29)
    job = new_job('cancel-prep', 'equilibrium_aware_namd', '', '')
    job.execution_target = 'runpod'
    job.status = MdStatus.preparing
    job.save(tmp_path)

    def prepare(_design, job_dir, **_kwargs):
        (job_dir / 'package').mkdir()
        (job_dir / 'package' / 'manifest.json').write_text('{}')
        stopped = MdJob.load(job.job_id, tmp_path)
        stopped.user_stopped = True
        stopped.status = MdStatus.stopped
        stopped.save(tmp_path)
        return 'package', 'test', []

    monkeypatch.setattr(routes_md, 'prepare_equilibrium_aware_namd', prepare)
    monkeypatch.setattr(routes_md, 'prepare_mgh_slow_release', prepare)
    monkeypatch.setattr(routes_md, '_start_runpod_job', lambda *_a: pytest.fail('autostart after Stop'))
    asyncio.run(routes_md._prepare_job_bg(
        job_id=job.job_id, body=body, design=Design(), seeded=False,
        ion_conc_mM=0, mg_conc_mM=0,
        tracker=PrepTracker(build_prep_phases(seeded=False), clock=lambda: 0.0),
    ))
    result = MdJob.load(job.job_id, tmp_path)
    assert result.status == MdStatus.stopped
    assert result.user_stopped
    assert result.package_subdir == 'package'
