import asyncio
from types import SimpleNamespace

import pytest

from backend.api import md_uv_crosslinking as api


def test_complete_cache_does_not_start_worker(monkeypatch):
    from backend.core import md_analysis_runner
    monkeypatch.setattr(api,'inputs',lambda job:('psf',['dcd'],None,'cache',{}))
    monkeypatch.setattr(api.uv,'read_result',lambda folder:{'complete':True,'ready':True})
    async def forbidden(*args,**kwargs):
        pytest.fail('complete cache started a trajectory worker')
    monkeypatch.setattr(md_analysis_runner,'run_analysis',forbidden)
    assert asyncio.run(api.result('job',None))['cached']


def test_disconnect_cancels_only_its_own_request(monkeypatch):
    from backend.core import md_analysis_runner
    monkeypatch.setattr(api,'inputs',lambda job:('psf',['dcd'],None,'cache',{}))
    monkeypatch.setattr(api.uv,'read_result',lambda folder:None)
    monkeypatch.setattr(md_analysis_runner,'cancel',lambda *args:pytest.fail('broad cancellation can kill a replacement'))
    async def worker(*args,**kwargs):
        await asyncio.sleep(100)
    async def disconnected():return True
    monkeypatch.setattr(md_analysis_runner,'run_analysis',worker)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(api.result('job',SimpleNamespace(is_disconnected=disconnected)))
    assert 'job' not in api._ACTIVE


def test_progress_follows_active_snapshot_when_trajectory_grows(monkeypatch):
    monkeypatch.setattr(api,'_ACTIVE',{'job':(object(),'original-cache')})
    monkeypatch.setattr(api,'inputs',lambda job:pytest.fail('progress recomputed changing fingerprint'))
    monkeypatch.setattr(api.uv,'progress',lambda folder:{'folder':folder,'done':10})
    assert asyncio.run(api.progress('job'))=={'folder':'original-cache','done':10}
