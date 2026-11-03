import asyncio
import threading
from types import SimpleNamespace

import pytest

from backend.core import memory_budget as budget, namd_runner


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path,monkeypatch):
    monkeypatch.setenv('NADOC_MEMORY_BUDGET_DIR',str(tmp_path/'budget'))


def test_health_holds_slot_through_repeated_cancellation(monkeypatch):
    started=threading.Event();finish=threading.Event()
    def check():
        started.set()
        assert finish.wait(5)
        return 'finished'
    monkeypatch.setattr(namd_runner,'run_health_check',check)
    async def scenario():
        task=asyncio.create_task(namd_runner._scheduled_health())
        while not started.is_set():await asyncio.sleep(.01)
        task.cancel();await asyncio.sleep(.01)
        task.cancel();await asyncio.sleep(.01)
        assert not task.done()
        waiter=budget.TrajectoryActivity('playback')
        try:
            assert not waiter.try_acquire()
            finish.set()
            with pytest.raises(asyncio.CancelledError):await task
            assert waiter.try_acquire()
        finally:finish.set();waiter.close()
    asyncio.run(scenario())
    assert not budget._records(budget._directory())


def test_inflight_health_defers_without_blocking_disk_monitor(tmp_path,monkeypatch):
    monkeypatch.setattr(namd_runner,'_INFLIGHT_HEALTH_FIRST_S',0)
    job=SimpleNamespace(run_kind='equilibrium_aware',job_id='probe',name_stem='input',
        health_probe=None,save=lambda _:None)
    spec=SimpleNamespace(name='seg',min_c1_paired=.9,min_wc_ref_relative=.85)
    output=tmp_path/'output';output.mkdir();(output/'seg.dcd').write_bytes(b'frames')
    def forbidden(*a,**kw):pytest.fail('Health overlapped playback')
    monkeypatch.setattr(namd_runner,'run_health_check',forbidden)
    lease=budget.TrajectoryActivity('playback');assert lease.try_acquire()
    try:
        tick=namd_runner._make_inflight_health_tick(job,spec,tmp_path,output,tmp_path)
        asyncio.run(asyncio.wait_for(tick(),.2))
        assert 'trajectory processing' in job.health_probe['reason']
        assert len(budget._records(budget._directory()))==1
    finally:lease.close()
