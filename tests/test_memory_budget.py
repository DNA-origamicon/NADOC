import json
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading

import pytest

from backend.core import memory_budget as budget


@pytest.fixture(autouse=True)
def isolated_budget(tmp_path, monkeypatch):
    monkeypatch.setenv('NADOC_MEMORY_BUDGET_DIR', str(tmp_path/'reservations'))
    monkeypatch.setattr(budget.psutil, 'virtual_memory', lambda: SimpleNamespace(available=8*1024**3))


def test_concurrent_requests_cannot_spend_same_capacity():
    release = threading.Event()
    acquired = threading.Event()
    def first():
        with budget.reserve(3*1024**3):
            acquired.set()
            release.wait(5)
    with ThreadPoolExecutor(2) as pool:
        future = pool.submit(first)
        assert acquired.wait(5)
        try:
            with pytest.raises(budget.MemoryBudgetExceeded):
                with budget.reserve(2*1024**3):
                    pytest.fail('overcommitted')
        finally:
            release.set()
        future.result()
    assert budget.available_for_work() == 4*1024**3


def test_exception_releases_reservation():
    with pytest.raises(RuntimeError):
        with budget.reserve(1024, kind='simulation'):
            assert budget.simulation_active()
            raise RuntimeError('cancel')
    assert not budget.simulation_active()


def test_stale_pid_identity_is_reclaimed():
    root = budget._directory()
    (root/'dead.json').write_text(json.dumps({
        'owner': {'pid': os.getpid(), 'created': -1}, 'child': None,
        'kind':'simulation','bytes':10**12}))
    assert budget.available_for_work() == 4*1024**3


def test_corrupt_reservation_fails_closed():
    (budget._directory()/'unknown.json').write_text('{')
    with pytest.raises(budget.MemoryBudgetExceeded):
        budget.available_for_work()


def test_valid_json_with_unknown_reservation_schema_fails_closed():
    (budget._directory()/'unknown.json').write_text('{}')
    with pytest.raises(budget.MemoryBudgetExceeded):
        budget.available_for_work()


def test_multiple_gpu_layout_requires_separate_qualification():
    with pytest.raises(budget.MemoryBudgetExceeded, match='one numeric GPU'):
        with budget.reserve(1024, gpu_mib=1000, devices='0,1'):
            pytest.fail('unqualified GPU layout admitted')


def test_child_usage_credits_only_existing_private_pages(monkeypatch):
    child=SimpleNamespace(memory_full_info=lambda: SimpleNamespace(uss=100))
    monkeypatch.setattr(budget,'_process',lambda identity: child)
    assert budget._remaining({'bytes':150,'child':{}})==50
    assert budget._remaining({'bytes':50,'child':{}})==0


def test_gpu_reservations_are_checked_atomically(monkeypatch):
    from backend.core import md_vram
    monkeypatch.setattr(md_vram,'detect_gpu_activity',lambda **kw:{'total_mb':12000,'used_mb':1000})
    with budget.reserve(1024,gpu_mib=7000):
        with pytest.raises(budget.MemoryBudgetExceeded):
            with budget.reserve(1024,gpu_mib=5000):
                pass


def test_trajectory_buffer_is_rejected_before_allocation():
    with pytest.raises(budget.MemoryBudgetExceeded,match='smaller frame range'):
        budget.check_array_budget(129*1024**2)


def test_second_process_observes_reservations():
    import subprocess
    import sys
    code = '''
from types import SimpleNamespace
from backend.core import memory_budget as b
b.psutil.virtual_memory=lambda: SimpleNamespace(available=8*1024**3)
try:
    with b.reserve(2*1024**3):
        raise SystemExit(2)
except b.MemoryBudgetExceeded:
    pass
'''
    with budget.reserve(3*1024**3):
        result = subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr


def test_heavy_analysis_waits_then_prevents_new_simulation_overlap():
    waiting=threading.Event();entered=threading.Event();release=threading.Event()
    def analyze():
        with budget.exclusive_analysis(on_wait=lambda _:waiting.set(),poll_seconds=.01):
            entered.set();release.wait(5)
    with ThreadPoolExecutor(1) as pool:
        with budget.reserve(1024,kind='simulation'):
            future=pool.submit(analyze)
            assert waiting.wait(5)
            assert not entered.is_set()
        assert entered.wait(5)
        try:
            with pytest.raises(budget.WorkloadBusy):
                with budget.reserve(1024,kind='simulation'):
                    pytest.fail('Simulation overlapped heavy analysis')
        finally:
            release.set()
        future.result()
    with budget.reserve(1024,kind='simulation'):
        assert budget.simulation_active()


def test_nested_analysis_shares_lease_without_claiming_a_memory_bound():
    with budget.exclusive_analysis():
        with budget.exclusive_analysis():
            records=budget._records(budget._directory())
            assert len(records)==2
            assert {r['kind'] for r in records} == {'heavy_analysis','trajectory_activity'}
            assert all(r['scheduling_only'] and r['bytes']==0 for r in records)
            assert budget.available_for_work()==4*1024**3


def test_queued_analysis_can_cancel_without_leaving_a_lease():
    cancel=threading.Event()
    with budget.reserve(1024,kind='simulation'):
        with pytest.raises(InterruptedError):
            with budget.exclusive_analysis(cancel=cancel,on_wait=lambda _:cancel.set()):
                pytest.fail('Cancelled work started')
        assert len(budget._records(budget._directory()))==1


def test_analysis_exclusion_is_visible_across_processes():
    import subprocess
    import sys
    code='''
from backend.core.memory_budget import reserve, WorkloadBusy
try:
    with reserve(1024,kind='simulation'):
        raise SystemExit(2)
except WorkloadBusy:
    pass
'''
    with budget.exclusive_analysis():
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_trajectory_queue_prioritizes_health_then_fifo():
    tickets=[budget.TrajectoryActivity(k) for k in ('playback','playback','health','bulk')]
    try:
        assert tickets[0].try_acquire()
        assert not any(t.try_acquire() for t in tickets[1:])
        tickets[0].close()
        assert not tickets[1].try_acquire()
        assert tickets[2].try_acquire()
        tickets[2].close()
        assert not tickets[3].try_acquire()
        assert tickets[1].try_acquire()
        tickets[1].close()
        assert tickets[3].try_acquire()
    finally:
        for t in tickets:t.close()
    assert not budget._records(budget._directory())


def test_cancelled_trajectory_waiter_leaves_no_ticket():
    import asyncio
    active=budget.TrajectoryActivity('health');assert active.try_acquire()
    async def waiter():
        async with budget.trajectory_activity('playback'):
            pytest.fail('overlapped active health')
    async def scenario():
        task=asyncio.create_task(waiter());await asyncio.sleep(.1)
        assert len(budget._records(budget._directory()))==2
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert len(budget._records(budget._directory()))==1
    try:asyncio.run(scenario())
    finally:active.close()


def test_trajectory_slot_is_visible_in_another_process():
    import subprocess,sys
    lease=budget.TrajectoryActivity('health');assert lease.try_acquire()
    code='''
from backend.core.memory_budget import TrajectoryActivity
lease=TrajectoryActivity('playback')
try:
    assert not lease.try_acquire()
finally:lease.close()
'''
    try:
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
    finally:lease.close()


def test_live_worker_retains_slot_after_owner_exit():
    lease=budget.TrajectoryActivity('health');assert lease.try_acquire()
    lease.bind_child(os.getpid())
    record=json.loads(lease.path.read_text());record['owner']['created']=-1
    lease.path.write_text(json.dumps(record))
    pending=budget.TrajectoryActivity('playback')
    try:assert not pending.try_acquire()
    finally:pending.close();lease.close()


def test_bulk_reclaims_idle_playback_after_acquiring_slot(monkeypatch):
    from backend.core import md_playback_workers as pool
    reclaimed=[]
    def close():
        assert budget.current_trajectory_activity() is not None
        reclaimed.append(True)
    monkeypatch.setattr(pool,'close',close)
    with budget.exclusive_analysis():assert reclaimed==[True]
