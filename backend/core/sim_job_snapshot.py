"""Fast, read-only job membership from local manifests.

No reconciliation, remote-drive probes, trajectory preparation or provenance hashes.
Status is the last saved status; the normal job endpoint refreshes it afterward.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from backend.core import sim_jobs
from backend.core.job_archive import read_index

_NORMALIZERS = {
    "oxdna": sim_jobs.normalize_oxdna_job,
    "lammps": sim_jobs.normalize_lammps_job,
    "mrdna": sim_jobs.normalize_mrdna_job,
    "cando": sim_jobs.normalize_cando_job,
    "snupi": sim_jobs.normalize_snupi_job,
    "blade": sim_jobs.normalize_blade_job,
    "md": sim_jobs.normalize_md_job,
}


@lru_cache(maxsize=4096)
def _read_manifest(path: Path, mtime_ns: int, size: int) -> dict:
    # Atomic saves replace the manifest; stat keys also detect other processes' saves.
    row = json.loads(path.read_text())
    if not isinstance(row, dict) or not row.get("job_id"):
        return {}
    row.pop("health_samples", None)
    return row


def read_snapshot(workspace: Path) -> list[dict]:
    nodes = []
    for engine, normalize in _NORMALIZERS.items():
        folder = workspace / f"{engine}_jobs"
        # Archive metadata stays local even when the artifact drive is disconnected.
        paths = {p.parent.name: p for p in folder.glob("*/job.json")}
        for job_id in read_index(workspace, f"{engine}_jobs"):
            paths.setdefault(job_id, folder / ".archive_metadata" / f"{job_id}.json")
        for path in paths.values():
            try:
                stat = path.stat()
                row = _read_manifest(path, stat.st_mtime_ns, stat.st_size)
                if row:
                    nodes.append(normalize({**row, "status_pending": True}))
            except (OSError, ValueError, TypeError):
                continue
    return nodes
