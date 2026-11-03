"""Killable subprocess runner for MD trajectory analysis."""

from __future__ import annotations

import asyncio
import time
import pytest

from backend.core import md_analysis_runner as R


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv('NADOC_MEMORY_BUDGET_DIR',str(tmp_path/'budget'))


def test_queued_bulk_analysis_starts_after_simulation_without_spending_timeout(tmp_path,monkeypatch):
    from backend.core import memory_budget as budget
    monkeypatch.setenv('NADOC_MEMORY_BUDGET_DIR',str(tmp_path/'budget'))
    monkeypatch.setattr(R,'_BULK',{'hypot'})
    async def admitted(*args,timeout_s):
        assert timeout_s==.2
        assert not budget.simulation_active()
        return 5.
    monkeypatch.setattr(R,'_run_analysis_admitted',admitted)
    async def scenario():
        with budget.reserve(1024,kind='simulation'):
            task=asyncio.create_task(R.run_analysis('queue','rmsf','math','hypot',(3.,4.),timeout_s=.2))
            await asyncio.sleep(.35)
            assert R.active_count()==0 and not task.done()
        # Verify the execution budget passed after queueing, independently of
        # variable subprocess spawn time (covered by the worker tests below).
        return await task
    assert asyncio.run(scenario())==5.


def test_pending_bulk_analysis_is_cancellable_without_starting_worker(tmp_path,monkeypatch):
    import pytest
    from backend.core import memory_budget as budget
    monkeypatch.setenv('NADOC_MEMORY_BUDGET_DIR',str(tmp_path/'budget'))
    monkeypatch.setattr(R,'_BULK',{'hypot'})
    async def scenario():
        with budget.reserve(1024,kind='simulation'):
            task=asyncio.create_task(R.run_analysis('cancel-queue','rmsf','math','hypot',(3.,4.)))
            await asyncio.sleep(.15)
            assert R.cancel('cancel-queue')==1
            with pytest.raises(asyncio.CancelledError):await task
        assert R.active_count()==0
    asyncio.run(scenario())


def test_runs_and_returns_result():
    out = asyncio.run(R.run_analysis("J", "rmsf", "math", "hypot", (3.0, 4.0)))
    assert out == 5.0
    assert R.active_count() == 0  # cleaned up


def test_timeout_kills_the_worker():
    t0 = time.monotonic()
    try:
        asyncio.run(R.run_analysis("J", "traj", "time", "sleep", (30,), timeout_s=1.0))
        assert False, "expected TimeoutError"
    except TimeoutError:
        pass
    assert time.monotonic() - t0 < 6.0  # killed promptly, not after 30s
    assert R.active_count() == 0


def test_cancel_kills_in_flight_analysis():
    async def scenario():
        task = asyncio.create_task(
            R.run_analysis("J", "rmsf", "time", "sleep", (30,), timeout_s=60)
        )
        await asyncio.sleep(1.0)  # let the worker start
        assert R.active_count() == 1
        killed = R.cancel("J", "rmsf")
        assert killed == 1
        # the awaiting task observes the kill as a worker-died error
        try:
            await task
        except Exception:
            pass
        assert R.active_count() == 0

    asyncio.run(scenario())


def test_new_request_supersedes_previous_for_same_view():
    async def scenario():
        first = asyncio.create_task(
            R.run_analysis("J", "rmsf", "time", "sleep", (30,), timeout_s=60)
        )
        await asyncio.sleep(1.0)
        assert R.active_count() == 1
        # a second request for the SAME (job, kind) kills the first
        second = asyncio.create_task(
            R.run_analysis("J", "rmsf", "math", "hypot", (6.0, 8.0), timeout_s=60)
        )
        result = await second
        assert result == 10.0
        try:
            await first
        except Exception:
            pass
        assert R.active_count() == 0

    asyncio.run(scenario())


def test_subprocess_self_timeout_via_alarm():
    """The worker self-terminates on its SIGALRM deadline even if the parent never
    gets to kill it (parent event loop starved) — the robust backstop."""
    import os
    import tempfile
    import time

    fd, rp = tempfile.mkstemp()
    os.close(fd)
    p = R._CTX.Process(
        target=R._target, args=(rp, "time", "sleep", (30,), 2.0), daemon=True
    )
    t0 = time.monotonic()
    p.start()
    p.join(timeout=12)
    elapsed = time.monotonic() - t0
    alive = p.is_alive()
    if alive:
        p.kill()
    os.unlink(rp) if os.path.exists(rp) else None
    assert not alive and elapsed < 8.0  # killed by its own 2s alarm, not the 30s sleep


def test_cancel_for_whole_job_kills_every_view():
    async def scenario():
        a = asyncio.create_task(
            R.run_analysis("J", "rmsf", "time", "sleep", (30,), timeout_s=60)
        )
        b = asyncio.create_task(
            R.run_analysis("J", "traj", "time", "sleep", (30,), timeout_s=60)
        )
        await asyncio.sleep(1.0)
        assert R.active_count() == 2
        assert R.cancel("J") == 2  # kind=None → all views for the job
        for t in (a, b):
            try:
                await t
            except Exception:
                pass
        assert R.active_count() == 0

    asyncio.run(scenario())


def test_playback_reuses_idle_interpreter_but_cancellation_kills_it(monkeypatch):
    from backend.core import md_playback_workers as pool
    monkeypatch.setattr(R, '_PLAYBACK', {'getpid', 'sleep'})
    async def scenario():
        pid = await R.run_analysis('pool', 'atoms', 'os', 'getpid', ())
        assert await R.run_analysis('pool', 'atoms', 'os', 'getpid', ()) == pid
        task = asyncio.create_task(R.run_analysis('pool', 'atoms', 'time', 'sleep', (30,)))
        await asyncio.sleep(.1)
        assert R.cancel('pool') == 1
        try:
            await task
        except RuntimeError:
            pass
        assert await R.run_analysis('pool', 'atoms', 'os', 'getpid', ()) != pid
        assert R.active_count() == 0
    try:
        asyncio.run(scenario())
    finally:
        pool.close()


def test_distinct_views_and_jobs_share_one_trajectory_slot(monkeypatch):
    monkeypatch.setattr(R,'_INTERACTIVE',{'hypot'})
    running=0;maximum=0
    async def admitted(*args,timeout_s):
        nonlocal running,maximum
        running+=1;maximum=max(maximum,running)
        await asyncio.sleep(.1)
        running-=1
        return args[4]
    monkeypatch.setattr(R,'_run_analysis_admitted',admitted)
    async def scenario():
        return await asyncio.gather(*(R.run_analysis(str(i),'atoms','math','hypot',(i,)) for i in range(3)))
    assert asyncio.run(scenario())==[(0,),(1,),(2,)]
    assert maximum==1


def test_playback_wait_is_cancellable_before_worker_creation(monkeypatch):
    from backend.core import memory_budget as budget
    monkeypatch.setattr(R,'_PLAYBACK',{'getpid'})
    active=budget.TrajectoryActivity('health');assert active.try_acquire()
    async def scenario():
        task=asyncio.create_task(R.run_analysis('waiting','atoms','os','getpid',()))
        await asyncio.sleep(.1)
        assert R.active_count()==0
        assert R.cancel('waiting')==1
        with pytest.raises(asyncio.CancelledError):await task
    try:asyncio.run(scenario())
    finally:active.close()
    assert not budget._records(budget._directory())


def test_playback_drops_idle_worker_during_simulation():
    from backend.core import memory_budget as budget, md_playback_workers as pool
    # Use real workers to verify termination, not just pool bookkeeping.
    async def scenario():
        with budget.reserve(1024,kind='simulation'):
            import psutil
            original=R._PLAYBACK
            R._PLAYBACK=original|{'getpid'}
            try:
                pid=await R.run_analysis('simulation','atoms','os','getpid',())
                assert not psutil.pid_exists(pid)
                assert not pool._idle
            finally:R._PLAYBACK=original
    try:asyncio.run(scenario())
    finally:pool.close()
