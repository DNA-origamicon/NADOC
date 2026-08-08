"""Unit tests for backend.core.disk_guard — output-size estimation, the free-space
forecast, and the in-run subprocess disk guard."""

import asyncio
import signal

from backend.core import disk_guard
from backend.core.disk_guard import (
    ABORT_MIN_FREE_BYTES,
    DISK_ABORT_RC,
    GiB,
    WARN_MIN_FREE_BYTES,
    forecast,
    free_bytes,
    namd_run_output_bytes,
    oxdna_run_output_bytes,
    wait_proc_with_disk_guard,
)


def test_free_bytes_walks_to_existing_ancestor(tmp_path):
    missing = tmp_path / "does" / "not" / "exist" / "yet"
    assert free_bytes(missing) > 0  # resolves to tmp_path's volume
    assert free_bytes(tmp_path) > 0


def test_namd_output_scales_with_atoms_and_steps():
    # (steps, dcd_freq) tuples: 100 frames of a 1000-atom system.
    small = namd_run_output_bytes([(100_000, 1_000)], 1_000)
    big = namd_run_output_bytes([(100_000, 1_000)], 10_000)
    assert big > small > 0
    # More frames → more bytes.
    more_frames = namd_run_output_bytes([(1_000_000, 1_000)], 1_000)
    assert more_frames > small
    # ≈ 12 bytes/atom/frame lower bound (100 frames * 1000 atoms * 12).
    assert small > 100 * 1_000 * 12


def test_namd_output_accepts_segmentspec_like_objects():
    class Seg:
        def __init__(self, steps, dcd_freq):
            self.steps, self.dcd_freq = steps, dcd_freq

    tuples = namd_run_output_bytes([(200_000, 2_000)], 5_000)
    objs = namd_run_output_bytes([Seg(200_000, 2_000)], 5_000)
    assert tuples == objs


def test_zero_particles_is_zero():
    assert namd_run_output_bytes([(100_000, 1_000)], 0) == 0
    assert oxdna_run_output_bytes([(100_000, 1_000)], 0) == 0


def test_oxdna_output_bounded_and_scales():
    # oxDNA prints ~100 configs regardless of length, so 10x steps at the same
    # 1/100 interval gives the same frame count → same size.
    a = oxdna_run_output_bytes([(1_000_000, 10_000)], 500)
    b = oxdna_run_output_bytes([(10_000_000, 100_000)], 500)
    assert a == b > 0
    # More nucleotides → bigger configs.
    assert oxdna_run_output_bytes([(1_000_000, 10_000)], 5_000) > a


def test_forecast_warns_below_threshold(monkeypatch, tmp_path):
    monkeypatch.setattr(disk_guard, "free_bytes", lambda _p: 12 * GiB)
    # Predicted output leaves 3 GB free → below the 10 GB warn floor.
    f = forecast(tmp_path, 9 * GiB)
    assert f["warn"] is True
    assert f["free_after_bytes"] == 3 * GiB
    assert f["warn_threshold_bytes"] == WARN_MIN_FREE_BYTES


def test_forecast_no_warn_with_headroom(monkeypatch, tmp_path):
    monkeypatch.setattr(disk_guard, "free_bytes", lambda _p: 100 * GiB)
    f = forecast(tmp_path, 5 * GiB)
    assert f["warn"] is False
    assert f["free_after_bytes"] == 95 * GiB


class _FakeProc:
    """Minimal asyncio-subprocess stand-in for the guard test."""

    def __init__(self, runtime_s, pid=4321):
        self._runtime = runtime_s
        self.pid = pid
        self.killed = False

    async def wait(self):
        if self.killed:
            return -signal.SIGTERM
        await asyncio.sleep(self._runtime)
        return 0


def test_guard_aborts_when_disk_drops(monkeypatch):
    monkeypatch.setattr(disk_guard, "free_bytes", lambda _p: ABORT_MIN_FREE_BYTES - 1)
    proc = _FakeProc(runtime_s=10.0)
    killed = {}

    def kill(pid):
        killed["pid"] = pid
        proc.killed = True

    rc = asyncio.run(wait_proc_with_disk_guard(proc, "/tmp", kill=kill, poll_s=0.05))
    assert rc == DISK_ABORT_RC
    assert killed["pid"] == proc.pid


def test_guard_returns_real_rc_with_headroom(monkeypatch):
    monkeypatch.setattr(disk_guard, "free_bytes", lambda _p: 100 * GiB)
    proc = _FakeProc(runtime_s=0.02)
    rc = asyncio.run(
        wait_proc_with_disk_guard(proc, "/tmp", kill=lambda _p: None, poll_s=0.05)
    )
    assert rc == 0


# ── on_tick: periodic hook for observing a long-running process ──────────────────
#
# Added for NAMD in-flight health sampling. Health used to be computed only after a
# segment FINISHED; a production run is one segment, so a 200 ns / 50M-step run produced
# exactly one sample ~13 hours in, and the health bar stayed empty the whole time.


class _TickProc:
    """A process that stays alive for `alive_polls` timeouts, then exits with rc=0."""

    def __init__(self, alive_polls: int):
        self.pid = 4242
        self._left = alive_polls

    async def wait(self):
        import asyncio

        if self._left > 0:
            self._left -= 1
            await asyncio.sleep(3600)  # outlive the poll timeout
        return 0


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_on_tick_fires_once_per_poll_while_the_process_runs(tmp_path):
    from backend.core.disk_guard import wait_proc_with_disk_guard

    calls = []
    rc = _run(
        wait_proc_with_disk_guard(
            _TickProc(3),
            tmp_path,
            kill=lambda _p: None,
            poll_s=0.01,
            on_tick=lambda: calls.append(1),
        )
    )
    assert rc == 0
    assert len(calls) == 3


def test_on_tick_may_be_async(tmp_path):
    from backend.core.disk_guard import wait_proc_with_disk_guard

    calls = []

    async def _tick():
        calls.append(1)

    rc = _run(
        wait_proc_with_disk_guard(
            _TickProc(2), tmp_path, kill=lambda _p: None, poll_s=0.01, on_tick=_tick
        )
    )
    assert rc == 0 and len(calls) == 2


def test_a_raising_on_tick_never_disturbs_the_run(tmp_path):
    """Monitoring must not be able to kill the job it is monitoring."""
    from backend.core.disk_guard import wait_proc_with_disk_guard

    killed = []

    def _boom():
        raise RuntimeError("health check exploded")

    rc = _run(
        wait_proc_with_disk_guard(
            _TickProc(2),
            tmp_path,
            kill=lambda p: killed.append(p),
            poll_s=0.01,
            on_tick=_boom,
        )
    )
    assert rc == 0  # the process still completes normally
    assert killed == []  # and is never killed


def test_on_tick_is_optional(tmp_path):
    """Omitting the hook reproduces the original behaviour exactly."""
    from backend.core.disk_guard import wait_proc_with_disk_guard

    assert (
        _run(
            wait_proc_with_disk_guard(
                _TickProc(2), tmp_path, kill=lambda _p: None, poll_s=0.01
            )
        )
        == 0
    )
