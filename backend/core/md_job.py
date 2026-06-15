"""
MD Job — persistent model for a managed NAMD simulation job.

Jobs live in workspace/md_jobs/{job_id}/job.json and survive server restarts.
Segment status and health samples are embedded in job.json; raw health/metrics
records are appended to output/health.jsonl and output/metrics.jsonl inside the
package directory.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class MdStatus(str, Enum):
    queued     = "queued"
    preparing  = "preparing"
    running    = "running"
    paused     = "paused"
    failed     = "failed"
    stopped    = "stopped"
    completed  = "completed"


@dataclass
class MdHealthSample:
    wall_time:               float
    stage:                   str
    segment:                 str
    c1_paired_fraction:      Optional[float] = None
    c1_mean_ang:             Optional[float] = None
    c1_p90_ang:              Optional[float] = None
    wc_ref_relative_fraction: Optional[float] = None
    wc_mean_hbond_ang:       Optional[float] = None
    passed:                  bool = True
    reason:                  str  = ""


@dataclass
class MdSegmentStatus:
    name:    str
    stage:   str
    percent: float
    steps:   int
    status:  str = "pending"   # pending / running / done / failed


@dataclass
class MdJob:
    job_id:              str
    design_name:         str
    protocol:            str
    status:              MdStatus
    created_at:          float
    package_subdir:      str        # relative path inside job_dir (e.g. "package/B_tube_namd_solvated")
    name_stem:           str        # PSF/PDB file stem (e.g. "B_tube")
    segments:            list[MdSegmentStatus]  = field(default_factory=list)
    current_segment_idx: int                    = 0
    error:               Optional[str]          = None
    namd_pid:            Optional[int]          = None
    threads:             int                    = 16
    devices:             str                    = "0"
    health_samples:      list[MdHealthSample]   = field(default_factory=list)
    design_source_path:  Optional[str]          = None
    seed_oxdna_job_id:   Optional[str]          = None  # provenance: oxDNA job whose relaxed coords seeded this run

    # ── Paths ──────────────────────────────────────────────────────────────────

    def job_dir(self, workspace_dir: Path) -> Path:
        return workspace_dir / "md_jobs" / self.job_id

    def package_dir(self, workspace_dir: Path) -> Path:
        return self.job_dir(workspace_dir) / self.package_subdir

    # ── Persistence ────────────────────────────────────────────────────────────

    def save(self, workspace_dir: Path) -> None:
        jd = self.job_dir(workspace_dir)
        jd.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["status"] = self.status.value
        (jd / "job.json").write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, job_id: str, workspace_dir: Path) -> "MdJob":
        path = workspace_dir / "md_jobs" / job_id / "job.json"
        data = json.loads(path.read_text())
        data["status"]   = MdStatus(data["status"])
        data["segments"] = [MdSegmentStatus(**s) for s in data.get("segments", [])]
        data["health_samples"] = [
            MdHealthSample(**h) for h in data.get("health_samples", [])
        ]
        data.setdefault("design_source_path", None)
        data.setdefault("seed_oxdna_job_id", None)
        return cls(**data)

    @classmethod
    def list_jobs(cls, workspace_dir: Path) -> list["MdJob"]:
        jobs_dir = workspace_dir / "md_jobs"
        if not jobs_dir.exists():
            return []
        result = []
        for jdir in sorted(jobs_dir.iterdir(), key=lambda p: p.name):
            json_path = jdir / "job.json"
            if json_path.exists():
                try:
                    result.append(cls.load(jdir.name, workspace_dir))
                except Exception:
                    pass
        return result

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        return data


def new_job(
    design_name: str,
    protocol: str,
    name_stem: str,
    package_subdir: str,
    *,
    threads: int = 16,
    devices: str = "0",
    design_source_path: Optional[str] = None,
    seed_oxdna_job_id: Optional[str] = None,
) -> MdJob:
    return MdJob(
        job_id         = uuid.uuid4().hex[:12],
        design_name    = design_name,
        protocol       = protocol,
        status         = MdStatus.queued,
        created_at     = time.time(),
        package_subdir = package_subdir,
        name_stem      = name_stem,
        threads        = threads,
        devices        = devices,
        design_source_path = design_source_path,
        seed_oxdna_job_id = seed_oxdna_job_id,
    )
