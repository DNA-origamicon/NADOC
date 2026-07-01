"""Archive / unarchive a simulation job's folder to / from an external location.

Heavy job folders (multi-GB trajectories) can be moved off the workspace onto an
archive directory anywhere on the host (e.g. an external drive) while keeping the
job's list entry and the ability to chain new jobs off it.

Mechanism
---------
* The job's data folder is **moved** out of ``workspace/{md_jobs,oxdna_jobs}/<id>``
  to ``<dest_root>/<id>``.
* A small index file ``workspace/<kind>/.archive_index.json`` maps
  ``job_id → archive_folder`` so ``load`` / ``list_jobs`` still discover the job
  even though its folder is no longer under the workspace.
* The job object carries ``archived`` / ``archive_path``; ``job_dir()`` resolves to
  the moved folder, so every consumer that reads job files through
  ``job_dir()`` / ``stage_dir()`` (including parent-of-a-chained-job reads) keeps
  working unchanged.

Moves run on a background thread with byte-level progress (some jobs are 40+ GB);
callers poll :func:`task_status`. The move is copy-then-delete so an interrupted
move never loses the source — a partial destination is cleaned up on failure.

One reason to change: where/how an archived job's bytes live and how the move is
tracked.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Optional

_INDEX_NAME = ".archive_index.json"

# ── Index ─────────────────────────────────────────────────────────────────────

def _index_path(workspace_dir: Path, kind: str) -> Path:
    return workspace_dir / kind / _INDEX_NAME


def read_index(workspace_dir: Path, kind: str) -> dict:
    """``{job_id: archive_folder}`` for the given job kind (empty if none)."""
    p = _index_path(workspace_dir, kind)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_index(workspace_dir: Path, kind: str, idx: dict) -> None:
    p = _index_path(workspace_dir, kind)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.parent / (_INDEX_NAME + ".tmp")
    tmp.write_text(json.dumps(idx, indent=2))
    tmp.replace(p)


def archived_job_ids(workspace_dir: Path, kind: str) -> list[str]:
    return list(read_index(workspace_dir, kind).keys())


def resolve_job_json(workspace_dir: Path, kind: str, job_id: str) -> Path:
    """Where this job's ``job.json`` currently lives (archive folder if archived)."""
    idx = read_index(workspace_dir, kind)
    if job_id in idx:
        return Path(idx[job_id]) / "job.json"
    return workspace_dir / kind / job_id / "job.json"


def purge_index_entry(workspace_dir: Path, kind: str, job_id: str) -> None:
    """Drop a job from the archive index (used when a job is deleted)."""
    idx = read_index(workspace_dir, kind)
    if job_id in idx:
        idx.pop(job_id, None)
        _write_index(workspace_dir, kind, idx)


# ── Move with progress ────────────────────────────────────────────────────────

def _tree_bytes(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue
    return total


def _copy_tree_with_progress(src: Path, dst: Path, progress: dict) -> None:
    """Copy ``src`` → ``dst`` recursively, updating ``progress['moved_bytes']``."""
    progress["total_bytes"] = _tree_bytes(src)
    moved = 0
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target = dst if rel == "." else dst / rel
        target.mkdir(parents=True, exist_ok=True)
        for fname in files:
            s = Path(root) / fname
            d = target / fname
            shutil.copy2(s, d)
            try:
                moved += d.stat().st_size
            except OSError:
                pass
            progress["moved_bytes"] = moved


# ── Task registry ─────────────────────────────────────────────────────────────

_TASKS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _task_key(kind: str, job_id: str) -> str:
    return f"{kind}:{job_id}"


def task_status(kind: str, job_id: str) -> Optional[dict]:
    """Current archive/unarchive task for a job, or None if idle/never run.

    Folds the live copy-loop byte counters into the snapshot and drops the
    internal ``_progress`` handle so the result is JSON-serialisable.
    """
    with _LOCK:
        t = _TASKS.get(_task_key(kind, job_id))
        if not t:
            return None
        snap = dict(t)
        prog = snap.pop("_progress", None)
        if prog and snap.get("state") == "running":
            snap["moved_bytes"] = prog["moved_bytes"]
            snap["total_bytes"] = prog["total_bytes"]
        return snap


def _set_task(kind: str, job_id: str, **fields) -> None:
    with _LOCK:
        key = _task_key(kind, job_id)
        t = _TASKS.setdefault(key, {"kind": kind, "job_id": job_id})
        t.update(fields)


def is_running(kind: str, job_id: str) -> bool:
    t = task_status(kind, job_id)
    return bool(t and t.get("state") == "running")


def _run_archive(job, workspace_dir: Path, kind: str, dest_root: Path) -> None:
    src = job.job_dir(workspace_dir)
    dest = dest_root / job.job_id
    progress = {"moved_bytes": 0, "total_bytes": 0}
    _set_task(kind, job.job_id, action="archive", state="running",
              dest=str(dest), moved_bytes=0, total_bytes=0, error=None)
    try:
        dest_root.mkdir(parents=True, exist_ok=True)
        # Point the task at the same dict the copy loop mutates so task_status()
        # reports live byte progress.
        _set_task(kind, job.job_id, _progress=progress)
        _copy_tree_with_progress(src, dest, progress)
        job.archived = True
        job.archive_path = str(dest)
        job.save(workspace_dir)                 # writes job.json into dest
        idx = read_index(workspace_dir, kind)
        idx[job.job_id] = str(dest)
        _write_index(workspace_dir, kind, idx)
        # Only after dest is complete.  rmtree refuses symlinks (silently, with
        # ignore_errors) — unlink those so a symlinked source never leaves a
        # duplicate behind (defence in depth; start_archive already blocks them).
        if src.is_symlink():
            src.unlink()
        else:
            shutil.rmtree(src, ignore_errors=True)
        _set_task(kind, job.job_id, state="done",
                  moved_bytes=progress["total_bytes"], total_bytes=progress["total_bytes"])
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(dest, ignore_errors=True)  # roll back the partial copy
        _set_task(kind, job.job_id, state="error", error=str(e))


def _run_unarchive(job, workspace_dir: Path, kind: str) -> None:
    src = Path(job.archive_path)
    dest = workspace_dir / kind / job.job_id
    progress = {"moved_bytes": 0, "total_bytes": 0}
    _set_task(kind, job.job_id, action="unarchive", state="running",
              dest=str(dest), moved_bytes=0, total_bytes=0, error=None)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _set_task(kind, job.job_id, _progress=progress)
        _copy_tree_with_progress(src, dest, progress)
        job.archived = False
        job.archive_path = None
        job.save(workspace_dir)                 # writes job.json into workspace dest
        purge_index_entry(workspace_dir, kind, job.job_id)
        shutil.rmtree(src, ignore_errors=True)
        _set_task(kind, job.job_id, state="done",
                  moved_bytes=progress["total_bytes"], total_bytes=progress["total_bytes"])
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(dest, ignore_errors=True)
        _set_task(kind, job.job_id, state="error", error=str(e))


def _check_archive_preconditions(job, workspace_dir: Path, kind: str, dest_root: Path) -> None:
    """Shared validation for archiving a job (async or sync).  Raises on any problem."""
    if job.archived:
        raise ValueError("job is already archived")
    if is_running(kind, job.job_id):
        raise ValueError("an archive operation is already in progress for this job")
    src = job.job_dir(workspace_dir)
    if not src.exists():
        raise FileNotFoundError(f"job folder not found: {src}")
    if src.is_symlink():
        # The job folder was manually relocated via a symlink (e.g. onto an
        # external drive).  Following it would COPY the data to a second location
        # and then fail to clean up the original (rmtree refuses symlinks),
        # leaving a duplicate.  Refuse with a clear message instead.
        raise ValueError(
            f"job folder is a symlink (already relocated to {os.path.realpath(src)}); "
            "archive does not apply — move or relink it manually"
        )
    dest = dest_root / job.job_id
    if dest.exists():
        raise FileExistsError(f"destination already exists: {dest}")
    if dest_root.resolve() == (workspace_dir / kind).resolve() or \
       _within(dest_root.resolve(), src.resolve()):
        raise ValueError("invalid archive destination")


def start_archive(job, workspace_dir: Path, kind: str, dest_root: Path) -> None:
    """Spawn the background archive move. Raises if it can't be started."""
    dest_root = Path(dest_root).expanduser()
    _check_archive_preconditions(job, workspace_dir, kind, dest_root)
    t = threading.Thread(target=_run_archive, args=(job, workspace_dir, kind, dest_root), daemon=True)
    t.start()


def archive_job(job, workspace_dir: Path, kind: str, dest_root: Path) -> str:
    """Synchronously archive a job's folder to ``dest_root/<job_id>`` (copy-then-delete),
    update the index + ``job.archived``, and return the archive path.

    The BLOCKING analog of :func:`start_archive` for headless / scripted callers — e.g. an
    experiment driver that archives each run to an external drive right after extracting its
    metrics, to keep the workspace from filling up over a long unattended series.  Same
    validation; raises ``RuntimeError`` if the move itself fails (the partial copy is rolled
    back by ``_run_archive``)."""
    dest_root = Path(dest_root).expanduser()
    _check_archive_preconditions(job, workspace_dir, kind, dest_root)
    _run_archive(job, workspace_dir, kind, dest_root)
    st = task_status(kind, job.job_id)
    if st and st.get("state") == "error":
        raise RuntimeError(f"archive failed: {st.get('error')}")
    return str(dest_root / job.job_id)


def start_unarchive(job, workspace_dir: Path, kind: str) -> None:
    if not job.archived or not job.archive_path:
        raise ValueError("job is not archived")
    if is_running(kind, job.job_id):
        raise ValueError("an archive operation is already in progress for this job")
    if not Path(job.archive_path).exists():
        raise FileNotFoundError(f"archived folder not found: {job.archive_path}")
    dest = workspace_dir / kind / job.job_id
    if dest.exists():
        raise FileExistsError(f"workspace folder already exists: {dest}")
    t = threading.Thread(target=_run_unarchive, args=(job, workspace_dir, kind), daemon=True)
    t.start()


def _within(child: Path, parent: Path) -> bool:
    try:
        return child == parent or child.is_relative_to(parent)
    except AttributeError:  # py < 3.9 fallback (unused on 3.12)
        return str(child).startswith(str(parent))
