"""Lightweight simulation metadata and location-aware artifact access."""

from __future__ import annotations

import json
from pathlib import Path
import time

from backend.core.job_cleanup import _job_classes
from backend.core.project_revisions import ProjectRevisionStore, _atomic_json


ACTIVE_STATUSES = {"draft", "queued", "preparing", "running", "paused"}


def _status(job) -> str:
    value = getattr(job, "status", "")
    return str(getattr(value, "value", value))


def _engine_for(cls) -> str:
    return cls.__module__.rsplit(".", 1)[-1].removesuffix("_job")


class ProjectArtifactCatalog:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.revisions = ProjectRevisionStore(workspace)

    def _path(self, project_id: str, engine: str, job_id: str) -> Path:
        safe = {c for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"}
        if not engine or not job_id or any(c not in safe for c in engine + job_id):
            raise ValueError("invalid artifact identity")
        return self.revisions._project(project_id) / "jobs" / engine / f"{job_id}.json"

    def publish_local_jobs(self, project_id: str | None = None) -> list[dict]:
        from backend.core.collaboration_peers import PeerRegistry

        identity = PeerRegistry(self.workspace).server_identity()
        published = []
        for cls in _job_classes():
            engine = _engine_for(cls)
            for job in cls.list_jobs(self.workspace):
                if not job.project_id or not job.design_revision_id:
                    continue
                if project_id is not None and job.project_id != project_id:
                    continue
                directory = job.job_dir(self.workspace)
                record = {
                    "format": "nadoc.project-job-metadata",
                    "schema_version": 1,
                    "project_id": job.project_id,
                    "design_revision_id": job.design_revision_id,
                    "engine": engine,
                    "job_id": job.job_id,
                    "design_name": job.design_name,
                    "status": _status(job),
                    "created_at": float(getattr(job, "created_at", 0)),
                    "parent_job_id": getattr(job, "parent_job_id", None),
                    "locations": [
                        {
                            "server_id": identity["id"],
                            "server_name": identity["name"],
                            "available": directory.is_dir(),
                            "active": _status(job) in ACTIVE_STATUSES,
                            "updated_at": time.time(),
                        }
                    ],
                }
                self.merge(record)
                published.append(record)
        return published

    def merge(self, incoming: dict) -> dict:
        if incoming.get("format") != "nadoc.project-job-metadata":
            raise ValueError("invalid project job metadata format")
        if incoming.get("schema_version") != 1:
            raise ValueError("unsupported project job metadata schema")
        required = ("project_id", "design_revision_id", "engine", "job_id", "locations")
        if any(not incoming.get(key) for key in required):
            raise ValueError("incomplete project job metadata")
        path = self._path(incoming["project_id"], incoming["engine"], incoming["job_id"])
        existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        merged = dict(existing or incoming)
        merged.update({key: value for key, value in incoming.items() if key != "locations"})
        locations = {
            location["server_id"]: location
            for location in (existing or {}).get("locations", [])
            if location.get("server_id")
        }
        for location in incoming["locations"]:
            if not location.get("server_id"):
                raise ValueError("artifact location has no server identity")
            locations[location["server_id"]] = location
        merged["locations"] = sorted(locations.values(), key=lambda item: item["server_id"])
        _atomic_json(path, merged)
        return merged

    def project_metadata(self, project_id: str) -> list[dict]:
        self.publish_local_jobs(project_id)
        root = self.revisions._project(project_id) / "jobs"
        records = []
        for path in sorted(root.glob("*/*.json")):
            records.append(json.loads(path.read_text(encoding="utf-8")))
        return records

    def local_job(self, project_id: str, engine: str, job_id: str):
        cls = next((item for item in _job_classes() if _engine_for(item) == engine), None)
        if cls is None:
            raise ValueError(f"unknown simulation engine: {engine}")
        job = cls.load(job_id, self.workspace)
        if job.project_id != project_id:
            raise ValueError("simulation job belongs to a different project")
        return job

    def list_files(self, project_id: str, engine: str, job_id: str) -> list[dict]:
        job = self.local_job(project_id, engine, job_id)
        directory = job.job_dir(self.workspace).resolve()
        files = []
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(directory).as_posix()
            files.append(
                {
                    "path": relative,
                    "size_bytes": path.stat().st_size,
                    "metadata": relative in {"job.json", "design.json"},
                }
            )
        return files

    def artifact_file(
        self, project_id: str, engine: str, job_id: str, relative_path: str
    ) -> Path:
        job = self.local_job(project_id, engine, job_id)
        root = job.job_dir(self.workspace).resolve()
        target = (root / relative_path).resolve()
        if not target.is_relative_to(root) or not target.is_file() or target.is_symlink():
            raise FileNotFoundError("artifact file is not available")
        return target

    def assert_fetchable(self, project_id: str, engine: str, job_id: str) -> None:
        job = self.local_job(project_id, engine, job_id)
        if _status(job) in ACTIVE_STATUSES:
            raise RuntimeError("active simulation artifacts cannot be copied")
