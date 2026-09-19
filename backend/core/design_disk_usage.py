"""Read-only on-disk size accounting for a design and its simulation data.

A design's total footprint on disk = the ``.nadoc`` file itself + every MD
(NAMD) and oxDNA job folder whose ``design_source_path`` points back at it (the
same linkage :mod:`backend.core.job_cleanup` uses to find orphaned jobs). This
module powers the welcome-screen "Data on disk" column and the Help ▸ About-this-
file panel. It only ever *reads* sizes — it never mutates jobs, designs, or the
topology (three-layer law: this is pure accounting over the physical layer).

One reason to change: how a design's on-disk footprint is measured and grouped.
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from pathlib import Path

from backend.core.job_cleanup import _norm
from backend.core.md_job import MdJob
from backend.core.oxdna_job import OxdnaJob


def dir_size_bytes(path: Path) -> int:
    """Total size of every regular file under ``path`` (0 if it doesn't exist).

    Cheap: stat-only, never reads file contents — a 27 GB / 1600-file job tree
    walks in a few milliseconds on local disk.  On a slow external drive a many-
    file tree is more expensive, so the polling hot paths use
    :func:`dir_size_bytes_cached`.
    """
    if not path.exists():
        return 0
    # os.scandir: the entry's file type comes free with the directory read and only
    # regular files are stat'd once, versus rglob + is_file + stat (two stats and a Path
    # object per file). Each syscall releases the GIL, so on a busy server the walk's
    # wall time scales with syscall count; this cut is what keeps a cold first walk of
    # ~160 job trees from stalling every other request.
    total = 0
    pending = [str(path)]
    while pending:
        try:
            with os.scandir(pending.pop()) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(entry.path)
                        elif entry.is_file():
                            total += entry.stat().st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


# Size on disk is informational and barely moves between polls, so a long TTL is
# plenty and keeps the job-list endpoints (polled every few seconds by the MD /
# oxDNA panels, across up to six engines) from re-walking multi-GB folders on a
# slow external drive each time — the bug that, alongside a heavy concurrent
# trajectory load, wedged the server during an 18hb archive.
#
# Was 60s. Measured directly (py-spy, aggregate over a real contended window):
# these directory walks — not GIL/CPU contention — were over half of ALL samples
# (dir_size_bytes's rglob+stat, 159 accumulated job directories across engines,
# some multi-GB NAMD trajectory packages) during a design load, because a poll
# every 4-5s guarantees some engine's 60s-old cache entry is always expiring and
# re-triggering a full background walk. 10 minutes cuts that re-walk frequency
# 10x for a column that's advisory, not live-progress (an ACTIVELY RUNNING job's
# growth is also visible through its own progress/health-sample fields, not only
# through this size poll).
_SIZE_TTL_S = 600.0
_size_cache: dict[str, tuple[float, int]] = {}
# Paths whose size is being walked right now, so overlapping polls of the same job
# list don't stampede a multi-GB directory. Guarded by _warm_lock (background walks
# run in a threadpool → real parallelism).
_warming: set[str] = set()
_warm_lock = threading.Lock()


def dir_size_bytes_cached(path: Path, ttl: float = _SIZE_TTL_S) -> int:
    """:func:`dir_size_bytes` memoised per path for ``ttl`` seconds."""
    key = str(path)
    now = time.time()
    hit = _size_cache.get(key)
    if hit is not None and now - hit[0] < ttl:
        return hit[1]
    val = dir_size_bytes(path)
    _size_cache[key] = (now, val)
    return val


def dir_size_bytes_cached_only(path: Path, ttl: float = _SIZE_TTL_S) -> int | None:
    """The cached size if it is fresh, else ``None`` — NEVER walks the directory.

    For the polled job-list endpoints: returning ``None`` immediately (instead of
    blocking on a multi-GB archived-trajectory walk on a slow external drive) keeps the
    panel responsive. The caller schedules :func:`warm_dir_sizes` in the background and
    the real size fills in on the next poll; the frontend renders a ``None`` size as
    blank until then.
    """
    hit = _size_cache.get(str(path))
    if hit is not None and time.time() - hit[0] < ttl:
        return hit[1]
    return None


def invalidate_dir_size(path: Path) -> None:
    """Drop a cached footprint after a transfer materially changes the directory."""
    with _warm_lock:
        _size_cache.pop(str(path), None)


def warm_dir_sizes(paths, ttl: float = _SIZE_TTL_S) -> None:
    """Walk + cache the size of each of ``paths`` that isn't already cached-fresh.

    Blocking (stat-walk I/O) — call from a threadpool / background task so the response
    isn't held. Deduped under ``_warm_lock`` so overlapping polls of the same list never
    launch two walks of the same directory (the check-and-claim of ``_warming`` is atomic).
    """
    for p in paths:
        key = str(p)
        with _warm_lock:
            hit = _size_cache.get(key)
            if key in _warming or (hit is not None and time.time() - hit[0] < ttl):
                continue
            _warming.add(key)  # claim it before releasing the lock
        try:
            size = dir_size_bytes(Path(p))
            with _warm_lock:
                _size_cache[key] = (time.time(), size)
        finally:
            with _warm_lock:
                _warming.discard(key)


# A single disk walker shared by all callers. Queue paths, not one task per poll.
_size_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nadoc-sizes")
_queued_paths: dict[str, Path] = {}
_warm_worker_running = False


def _drain_size_queue():
    global _warm_worker_running
    while True:
        with _warm_lock:
            if not _queued_paths:
                _warm_worker_running = False
                return
            key = next(iter(_queued_paths))
            path = _queued_paths.pop(key)
        try:
            warm_dir_sizes([path])
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Cannot measure job directory %s", path)


def schedule_dir_size_warm(paths) -> None:
    """Queue cold paths once; one dedicated worker performs all background walks."""
    global _warm_worker_running
    with _warm_lock:
        for path in paths:
            key = str(path)
            hit = _size_cache.get(key)
            if key not in _warming and (hit is None or time.time() - hit[0] >= _SIZE_TTL_S):
                _queued_paths[key] = Path(path)
        if _queued_paths and not _warm_worker_running:
            _warm_worker_running = True
            _size_executor.submit(_drain_size_queue)


def cached_sim_bytes_by_source_path(workspace_dir: Path) -> dict[str, int | None]:
    """Library accounting without directory walks. None means size is pending."""
    totals: dict[str, int | None] = {}
    pending = []
    for cls in (MdJob, OxdnaJob):
        for job in cls.list_jobs(workspace_dir):
            key = _norm(job.design_source_path)
            if not key:
                continue
            path = job.job_dir(workspace_dir)
            size = dir_size_bytes_cached_only(path)
            if size is None:
                pending.append(path)
                totals[key] = None
            elif key not in totals or totals[key] is not None:
                totals[key] = totals.get(key, 0) + size
    schedule_dir_size_warm(pending)
    return totals


def _status_str(job) -> str | None:
    st = getattr(job, "status", None)
    return st.value if hasattr(st, "value") else st


def _job_record(job, workspace_dir: Path, kind: str) -> dict:
    """One ``{kind, job_id, design_name, design_source_path, status, size_bytes}`` row."""
    return {
        "kind": kind,
        "job_id": job.job_id,
        "design_name": job.design_name,
        "design_source_path": job.design_source_path,
        "status": _status_str(job),
        "size_bytes": dir_size_bytes_cached(job.job_dir(workspace_dir)),
    }


def all_job_records(workspace_dir: Path) -> list[dict]:
    """Every MD + oxDNA job on disk as a size record (one pass over the job lists)."""
    records: list[dict] = []
    for j in MdJob.list_jobs(workspace_dir):
        records.append(_job_record(j, workspace_dir, "md"))
    for j in OxdnaJob.list_jobs(workspace_dir):
        records.append(_job_record(j, workspace_dir, "oxdna"))
    return records


def sim_bytes_by_source_path(workspace_dir: Path) -> dict[str, int]:
    """Map normalised ``design_source_path`` → total job bytes (MD + oxDNA).

    Built in a single pass so the library listing can look up every design's
    simulation footprint without re-scanning the job folders per row.
    """
    agg: dict[str, int] = {}
    for rec in all_job_records(workspace_dir):
        key = _norm(rec["design_source_path"])
        if not key:
            continue
        agg[key] = agg.get(key, 0) + rec["size_bytes"]
    return agg


def jobs_for_source_path(workspace_dir: Path, target_path: str) -> list[dict]:
    """Size records for the MD + oxDNA jobs tied to a single ``.nadoc`` path."""
    tgt = _norm(target_path)
    if not tgt:
        return []
    return [
        r
        for r in all_job_records(workspace_dir)
        if _norm(r["design_source_path"]) == tgt
    ]


def assemblies_referencing(workspace_dir: Path, target_path: str) -> list[dict]:
    """Workspace ``.nass`` assemblies that place this part via a file source.

    Each part instance's ``source.path`` is stored relative to the assembly file;
    it is resolved back to a workspace-relative path before comparison. Inline
    part sources (design embedded in the .nass) can't be matched by path and are
    ignored. Returns ``[{"name", "path"}, ...]``.
    """
    tgt = _norm(target_path)
    if not tgt:
        return []
    ws = workspace_dir.resolve()
    out: list[dict] = []
    for nass in workspace_dir.rglob("*.nass"):
        rel_parts = nass.relative_to(workspace_dir).parts
        if any(p.startswith(".") or p.startswith("__") for p in rel_parts):
            continue
        try:
            data = json.loads(nass.read_text())
        except (OSError, ValueError):
            continue
        nass_dir = nass.parent
        for inst in data.get("instances", []):
            src = inst.get("source") or {}
            if src.get("type") != "file" or not src.get("path"):
                continue
            try:
                resolved = (nass_dir / src["path"]).resolve().relative_to(ws)
                rel = _norm(str(resolved))
            except ValueError:
                rel = _norm(src["path"])
            if rel == tgt:
                out.append(
                    {
                        "name": nass.stem,
                        "path": _norm(str(nass.relative_to(workspace_dir))),
                    }
                )
                break
    return out
