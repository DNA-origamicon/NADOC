"""Killable, deduplicated runner for heavy MD trajectory analysis.

Trajectory / RMSF / surface analysis reads a live, *growing* 1M-atom DCD through
MDAnalysis, which re-scans the whole file to recompute frame offsets and can stall
for minutes inside a single C call.  Run in the request thread it is uncancellable:
toggling the view off leaves the work running, and repeated toggles pile up workers
that pin every core and exhaust RAM until the dev server looks hung.

This module runs each analysis in a dedicated **spawn** subprocess that becomes its
own session leader (``os.setsid``), so cancelling kills the whole process group —
including any worker processes the analysis libraries spawned internally.  Work is
keyed by ``(job_id, kind)``: starting a new analysis supersedes (kills) the previous
one for that view, a hard timeout bounds run-away calls, and an explicit
``cancel()`` (wired to the frontend toggle-off) tears it down immediately.
"""
from __future__ import annotations

import asyncio
import importlib
import multiprocessing
import os
import pickle
import signal
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

# spawn (not fork): the uvicorn worker is multi-threaded, and forking a threaded
# process can deadlock the child — exactly the failure that wedged the server.
_CTX = multiprocessing.get_context("spawn")

# (job_id, kind) -> (Process, result_path)
_active: dict[tuple[str, str], tuple[multiprocessing.process.BaseProcess, Path]] = {}
_lock = threading.Lock()

DEFAULT_TIMEOUT_S = 180.0


def _target(result_path: str, module: str, qualname: str, args: tuple,
            timeout_s: float) -> None:
    """Subprocess entry: own a fresh session, run the function, pickle the result.

    Self-enforces the timeout with ``SIGALRM`` so the worker dies on schedule even
    if the parent's asyncio loop is starved (e.g. another request doing synchronous
    MDAnalysis work) and never gets to kill it — the failure that let a worker run
    unbounded.  The default SIGALRM disposition terminates the process, which the
    kernel delivers regardless of what C call the worker is stuck in.
    """
    try:
        os.setsid()  # become process-group leader so the parent can killpg the tree
    except OSError:
        pass
    try:
        signal.alarm(max(1, int(timeout_s)))  # hard self-deadline, parent-independent
    except (ValueError, OSError):
        pass
    try:
        fn = getattr(importlib.import_module(module), qualname)
        out: tuple[str, Any] = ("ok", fn(*args))
    except BaseException as exc:  # noqa: BLE001 — report any failure to the parent
        out = ("err", f"{type(exc).__name__}: {exc}")
    try:
        with open(result_path, "wb") as fh:
            pickle.dump(out, fh)
    except Exception:  # noqa: BLE001,S110 — parent treats a missing result as failure
        pass


def _kill(proc: multiprocessing.process.BaseProcess) -> None:
    """Terminate a worker and any descendants, without touching the server's group."""
    pid = proc.pid
    if pid is None:
        return
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, OSError):
        return
    # Only group-kill when the child made its OWN group (setsid ran) — pgid == pid.
    # Otherwise it still shares the server's group, so kill just the child.
    group = pgid == pid
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig) if group else os.kill(pid, sig)
        except (ProcessLookupError, OSError):
            break
        proc.join(timeout=2.0)
        if not proc.is_alive():
            break


def cancel(job_id: str, kind: Optional[str] = None) -> int:
    """Kill the running analysis for ``(job_id, kind)`` — or every kind for the job
    when ``kind`` is None (view toggled off / job deselected). Returns how many were
    killed. Safe to call when nothing is running."""
    with _lock:
        keys = [
            k for k in _active
            if k[0] == job_id and (kind is None or k[1] == kind)
        ]
        victims = [(k, _active.pop(k)) for k in keys]
    for _key, (proc, result_path) in victims:
        _kill(proc)
        Path(result_path).unlink(missing_ok=True)
    return len(victims)


async def run_analysis(
    job_id: str,
    kind: str,
    module: str,
    qualname: str,
    args: tuple,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> Any:
    """Run ``module.qualname(*args)`` in a killable subprocess and return its result.

    Supersedes any in-flight analysis for the same ``(job_id, kind)``.  Raises
    ``asyncio.CancelledError`` (propagated to the HTTP layer) if the client
    disconnects or :func:`cancel` is called, and ``TimeoutError`` past
    ``timeout_s`` — in every exit path the subprocess group is killed.
    """
    cancel(job_id, kind)  # supersede the previous view request

    fd, result_name = tempfile.mkstemp(suffix=".pkl", prefix="md_analysis_")
    os.close(fd)
    result_path = Path(result_name)
    proc = _CTX.Process(
        target=_target, args=(result_name, module, qualname, args, timeout_s), daemon=True)
    proc.start()
    with _lock:
        _active[(job_id, kind)] = (proc, result_path)

    deadline = time.monotonic() + timeout_s
    try:
        while proc.is_alive():
            if time.monotonic() > deadline:
                raise TimeoutError(f"{kind} analysis exceeded {timeout_s:.0f}s")
            await asyncio.sleep(0.1)  # cancellation point — disconnect raises here
        try:
            status, payload = pickle.loads(result_path.read_bytes())
        except (FileNotFoundError, EOFError, pickle.UnpicklingError):
            raise RuntimeError(f"{kind} analysis worker died without a result") from None
        if status == "err":
            raise RuntimeError(payload)
        return payload
    except BaseException:
        _kill(proc)
        raise
    finally:
        with _lock:
            if _active.get((job_id, kind), (None, None))[0] is proc:
                _active.pop((job_id, kind), None)
        result_path.unlink(missing_ok=True)


def active_count() -> int:
    """Number of analyses currently running (for tests / diagnostics)."""
    with _lock:
        return len(_active)
