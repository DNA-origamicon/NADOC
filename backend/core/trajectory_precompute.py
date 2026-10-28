"""Quiet, serialized, low-priority precomputation of completed trajectory views.

The API only queues work. A separate single-core process owns trajectory parsing,
with one machine-wide lock so detached runners and API processes cannot compete.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

_LOG = logging.getLogger(__name__)
_QUEUE = queue.Queue()
_LOCK = threading.Lock()
_PENDING = set()
_RECENT = {}
_THREAD = None
_MEMORY_LIMITED = 76

# Previous manifests covered sampled MD analyses only. Keep existing artifacts,
# but backfill full-frame results before considering a job prepared.
COVERAGE = "all-written-frames-v2"

# Defer unattended work while simulations prepare/write data. Queued resumes
# can already contain stable frames; input discovery decides whether work exists.
_DEFER_BACKGROUND = {"draft", "preparing", "running"}


def _prepared(directory):
    from backend.core.trajectory_cache import VERSION

    try:
        record = json.loads((directory / "analysis_cache" / "prepared.json").read_text())
        if record["version"] != VERSION or record.get("coverage") != COVERAGE:
            return False
        # Compare the inventory too: a resumed job may add a new segment without
        # changing any of the trajectory files in the previous manifest.
        if record["sources"] != [list(row) for row in _source_stamp(directory)]:
            return False
        return bool(record["artifacts"]) and all(
            (directory / "analysis_cache" / name).is_file() for name in record["artifacts"]
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def schedule(job, workspace, engine):
    if os.environ.get("NADOC_PRECOMPUTE_WORKER") or job.status.value in _DEFER_BACKGROUND:
        return
    directory = job.job_dir(Path(workspace))
    if not directory.is_dir() or _prepared(directory):
        return
    key = (str(Path(workspace).resolve()), engine, job.job_id)
    global _THREAD
    with _LOCK:
        if key in _PENDING or time.monotonic() - _RECENT.get(key, -1000) < 60:
            return
        _PENDING.add(key)
        _QUEUE.put(key)
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(target=_drain, name="trajectory-precompute", daemon=True)
            _THREAD.start()


def _drain():
    while True:
        key = _QUEUE.get()
        interrupted = False
        memory_limited = False
        try:
            from backend.core.trajectory_priority import PREEMPTED, foreground_active

            while foreground_active():
                time.sleep(0.1)
            env = dict(os.environ, NADOC_PRECOMPUTE_WORKER="1", OMP_NUM_THREADS="1",
                       OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
            completed = subprocess.run(
                [sys.executable, "-m", __name__, *key],
                cwd=Path(__file__).resolve().parents[2], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=7200,
            )
            interrupted = completed.returncode == PREEMPTED
            memory_limited = completed.returncode == _MEMORY_LIMITED
            if completed.returncode and not interrupted:
                _LOG.warning("Trajectory precompute failed for %s: %s", key,
                             completed.stderr.decode(errors="replace")[-2000:])
        except Exception:
            _LOG.exception("Trajectory precompute failed for %s", key)
        finally:
            with _LOCK:
                if interrupted:
                    # Retain queue ownership; resume remaining artifacts after the
                    # click finishes (or its process is cancelled/crashes).
                    _QUEUE.put(key)
                else:
                    _PENDING.discard(key)
                    _RECENT[key] = time.monotonic() + (3540 if memory_limited else 0)
            _QUEUE.task_done()


def _source_stamp(directory):
    # Metadata only: no trajectory reads on a warm pass. Include logs, snapshots,
    # references and topology so resumed/downloaded jobs are naturally invalidated.
    return [(str(p.relative_to(directory)), p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(directory.rglob("*"))
            if p.is_file() and "analysis_cache" not in p.relative_to(directory).parts
            and not p.name.startswith(".") and not p.name.endswith(".tmp")]


def prepare(workspace, engine, job_id):
    from backend.core.simulation_runtime import use_workspace
    from backend.core.trajectory_cache import VERSION

    ws = Path(workspace)
    with use_workspace(ws):
        if engine == "md":
            from backend.core.md_job import MdJob
            from backend.api import routes_md_metrics as metrics
            from backend.core.md_trajectory import md_rmsf, md_rmsf_atomistic, md_rmsf_surface
            job = MdJob.load(job_id, ws)
            request = metrics.MdMetricsStartRequest(max_frames=0)
        else:
            from backend.core.oxdna_job import OxdnaJob
            from backend.api import routes_oxdna_metrics as metrics
            job = OxdnaJob.load(job_id, ws)
            request = metrics.MetricsStartRequest()
        if job.status.value in _DEFER_BACKGROUND:
            return
        directory = job.job_dir(ws)
        cache = directory / "analysis_cache"
        cache.mkdir(exist_ok=True)
        marker = cache / "prepared.json"
        stamp = json.dumps([VERSION, _source_stamp(directory)])
        if _prepared(directory):
            return
        inputs = metrics._job_inputs(job, ws)
        if inputs is None or isinstance(inputs, str):
            return
        if engine == "md":
            psf, ref, segments, design = inputs
            # A frozen snapshot is required for unattended work; never use another
            # open document as the reference for a legacy job.
            from backend.api.routes_md import _md_snapshot_design
            if _md_snapshot_design(job) is None:
                return
            args = (psf, segments, ref, design)
            md_rmsf(*args)
            md_rmsf_atomistic(*args, include_model=True)
            md_rmsf_surface(*args)
        else:
            from backend.api.routes_oxdna import _rmsf_average_frame
            _rmsf_average_frame(job, True)
        metrics._compute("precompute", job_id, request, ws)
        run = metrics._RUNS.pop("precompute", {})
        if run.get("state") == "error":
            raise RuntimeError(run.get("error"))
        result = run.get("result", {})
        if (result.get("ready") or result.get("not_applicable")) and stamp == json.dumps([VERSION, _source_stamp(directory)]):
            temp = marker.with_suffix(".tmp")
            temp.write_text(json.dumps({
                "version": VERSION, "coverage": COVERAGE, "sources": _source_stamp(directory),
                "artifacts": [p.name for p in cache.glob("*.json") if p != marker],
            }))
            temp.replace(marker)


def _limit_worker_memory():
    """Disposable analysis must never compete for all host RAM or swap."""
    import resource
    import psutil
    ceiling = min(2 * 1024**3, int(psutil.virtual_memory().available * 0.25))
    current = psutil.Process().memory_info().vms
    if ceiling < current + 128 * 1024**2:
        raise MemoryError('Insufficient memory for background trajectory analysis')
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard != resource.RLIM_INFINITY:
        ceiling = min(ceiling, hard)
    resource.setrlimit(resource.RLIMIT_AS, (ceiling, hard))


def main():
    import fcntl
    import tempfile

    os.environ["NADOC_PRECOMPUTE_WORKER"] = "1"
    _limit_worker_memory()
    os.nice(19)
    if hasattr(os, "sched_getaffinity"):
        os.sched_setaffinity(0, {max(os.sched_getaffinity(0))})
    # idle I/O class on Linux, when ionice is available
    try:
        subprocess.run(["ionice", "-c", "3", "-p", str(os.getpid())],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        pass
    with (Path(tempfile.gettempdir()) / f"nadoc-precompute-{os.getuid()}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        from backend.core import trajectory_priority as priority

        # Only computations inside the atomic artifact cache may be interrupted;
        # reference/snapshot preparation outside it must finish its file writes.
        priority.BACKFILL_PROCESS = True
        prepare(*sys.argv[1:])


if __name__ == "__main__":
    try:
        main()
    except MemoryError:
        print("Background trajectory analysis stopped at its memory limit; simulation data is unchanged.", file=sys.stderr)
        sys.exit(_MEMORY_LIMITED)
