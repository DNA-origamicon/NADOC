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
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue
    return total


# A short TTL is plenty: size on disk is informational and barely moves between
# polls. This keeps the job-list endpoints (polled every few seconds by the MD /
# oxDNA panels) from re-walking multi-GB folders on a slow external drive each
# time — the bug that, alongside a heavy concurrent trajectory load, wedged the
# server during an 18hb archive.
_SIZE_TTL_S = 60.0
_size_cache: dict[str, tuple[float, int]] = {}


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
    return [r for r in all_job_records(workspace_dir) if _norm(r["design_source_path"]) == tgt]


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
                out.append({
                    "name": nass.stem,
                    "path": _norm(str(nass.relative_to(workspace_dir))),
                })
                break
    return out
