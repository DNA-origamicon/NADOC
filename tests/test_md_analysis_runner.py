"""Killable subprocess runner for MD trajectory analysis."""

from __future__ import annotations

import asyncio
import time

from backend.core import md_analysis_runner as R


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
