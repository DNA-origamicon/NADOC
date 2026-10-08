"""Read simulation completion evidence without reconciling, launching or writing jobs."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

from backend.core.models import Design
from backend.core.oxdna_staleness import design_build_fingerprint


ENGINE_FOLDERS = {
    "oxdna": "oxdna_jobs", "mrdna": "mrdna_jobs", "cando": "cando_jobs",
    "snupi": "snupi_jobs", "namd": "md_jobs", "lammps": "lammps_jobs",
}
ENGINE_LABELS = {"oxdna": "oxDNA", "mrdna": "mrDNA", "cando": "CanDo", "snupi": "SNUPI", "namd": "NAMD", "lammps": "LAMMPS"}


def completed_simulation_kind(engine: str, job: dict) -> str | None:
    """Use each engine's persisted stage contract; preparation/coarse is insufficient."""
    if job.get("status") != "completed":
        return None
    done = [stage for stage in job.get("stages", []) if stage.get("status") == "done"]
    if engine in {"cando", "snupi"}:
        fine_stages = {"nonlinear"}
        if engine == "cando" and job.get("kind") == "autorefine":
            # The final cached prediction after refinement uses job.nonlinear.
            fine_stages.add("autorefine")
        if job.get("nonlinear") and any(stage.get("name") in fine_stages for stage in done):
            return "Fine"
    elif engine == "mrdna":
        if any(stage.get("name") == "fine" and stage.get("steps", 0) > 0 for stage in done):
            return "Fine"
    elif engine == "oxdna":
        if any(stage.get("kind") in {"production", "field"} and stage.get("steps", 0) > 0 for stage in done):
            return "Production"
    elif engine == "namd":
        from backend.core.md_job import _is_production_segment_name

        if any(
            segment.get("status") == "done" and not segment.get("skipped")
            and segment.get("steps", 0) > 0
            and (job.get("run_kind") == "production" or _is_production_segment_name(
                segment.get("name", ""), segment.get("stage", "")
            ))
            for segment in job.get("segments", [])
        ):
            return "Production"
    elif engine == "lammps" and job.get("steps", 0) > 0:
        return "Production"
    return None


def _stamp(path: Path):
    stat = path.stat()
    return str(path), stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=512)
def _read_json(path, _mtime, _size):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError("Job metadata must be an object.")
    # Health histories can be large. Retain only the completion/provenance
    # fields used here, rather than caching hundreds of complete job manifests.
    fields = {
        "job_id", "status", "project_id", "design_revision_id", "design_fingerprint",
        "parent_job_id", "kind", "run_kind", "nonlinear", "dynamics", "stages", "segments", "steps",
    }
    return {key: value for key, value in data.items() if key in fields}


@lru_cache(maxsize=128)
def _snapshot_identity(path, _mtime, _size):
    design = Design.from_json(Path(path).read_text())
    return design.id, design_build_fingerprint(design)


@lru_cache(maxsize=128)
def _revision_identity(workspace, project_id, revision_id, _mtime, _size):
    from backend.core.project_revisions import ProjectRevisionStore

    design = ProjectRevisionStore(Path(workspace)).load_design(project_id, revision_id)
    return design.id, design_build_fingerprint(design)


def _metadata_paths(workspace, folder):
    """Live and archived metadata without job.load()'s archive-cache writes."""
    from backend.core.job_archive import read_index

    root = workspace / folder
    paths = {path.parent.name: path for path in root.glob("*/job.json")}
    for job_id, archive in read_index(workspace, folder).items():
        if job_id in paths:
            continue
        try:
            live = Path(archive) / "job.json"
            cached = root / ".archive_metadata" / f"{job_id}.json"
            paths[job_id] = live if live.is_file() else cached
        except (OSError, ValueError, TypeError):
            continue  # One malformed archival entry cannot hide live jobs.
    return paths


def _job_identity(job, path, paths, workspace):
    """Resolve the immutable snapshot, including production-parent inheritance."""
    current, current_path, seen = job, path, set()
    while current_path not in seen:
        seen.add(current_path)
        snapshot = current_path.parent / "design.json"
        if snapshot.is_file():
            return _snapshot_identity(*_stamp(snapshot))
        parent_id = current.get("parent_job_id")
        if not parent_id or parent_id not in paths:
            break
        current_path = paths[parent_id]
        current = _read_json(*_stamp(current_path))
    project, revision = job.get("project_id"), job.get("design_revision_id")
    if project and revision:
        from backend.core.project_revisions import ProjectRevisionStore

        revision_path = ProjectRevisionStore(workspace).object_path(project, revision)
        if revision_path.is_file():
            _, mtime, size = _stamp(revision_path)
            return _revision_identity(str(workspace), project, revision, mtime, size)
    # Positive exact stored hashes can qualify modern archived metadata even if
    # the archive is offline. Unknown/legacy hashes never become a pass.
    return project, job.get("design_fingerprint")


def completed_simulation(design: Design | str, workspace: Path, fingerprint: str | None = None) -> dict:
    """Return one completed, current-design Fine/Production run, or explain its absence."""
    design_id = design if isinstance(design, str) else design.id
    if fingerprint is None:
        if isinstance(design, str):
            raise ValueError("A design ID requires its current build fingerprint.")
        fingerprint = design_build_fingerprint(design)
    stale = unknown = unreadable = 0
    for engine, folder in ENGINE_FOLDERS.items():
        try:
            paths = _metadata_paths(workspace, folder)
        except (OSError, ValueError, TypeError):
            unreadable += 1
            continue
        for job_id, path in paths.items():
            try:
                job = _read_json(*_stamp(path))
                kind = completed_simulation_kind(engine, job)
                if not kind:
                    continue
                project = job.get("project_id")
                if project and project != design_id:
                    continue
                snapshot_id, saved_fingerprint = _job_identity(job, path, paths, workspace)
                if (project or snapshot_id) != design_id:
                    continue
                if not saved_fingerprint or not str(saved_fingerprint).startswith(fingerprint.split(":", 1)[0] + ":"):
                    unknown += 1
                    continue
                if saved_fingerprint != fingerprint:
                    stale += 1
                    continue
                return {
                    "complete": True, "action": "simulation", "job_id": job_id,
                    "engine": engine, "kind": kind,
                    "detail": f"{ENGINE_LABELS[engine]} {kind} completed for the current design. This is not a convergence or folding-yield assessment.",
                }
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                unreadable += 1
    detail = "Complete Fine (mrDNA, CanDo, SNUPI) or Production (oxDNA, NAMD, LAMMPS) for the current design."
    if stale:
        detail += f" {stale} completed run(s) belong to an earlier design state."
    if unknown:
        detail += f" {unknown} completed run(s) lack verifiable design provenance."
    if unreadable:
        detail += f" {unreadable} job record(s) could not be checked."
    return {
        "complete": False, "action": "simulation", "detail": detail,
        "stale_runs": stale, "unknown_runs": unknown, "unreadable_records": unreadable,
    }
