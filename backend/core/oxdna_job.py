"""
oxDNA Job — persistent model for a managed local oxDNA relaxation job.

Sibling of ``md_job.py`` (the NAMD job model).  Jobs live in
``workspace/oxdna_jobs/{job_id}/job.json`` and survive server restarts.  Each
job runs a fixed 3-stage coarse-grained relaxation protocol (min → MD relax →
equilibrate); per-stage status and health samples are embedded in job.json, and
raw health/metrics records are appended to ``{job_dir}/health.jsonl`` and
``{job_dir}/metrics.jsonl``.

Architecture note: oxDNA output is **Physical-layer / display state only**.  A
job's relaxed positions are read back for display (deforming the NADOC model)
but are NEVER written into Design topology.  See CLAUDE.md Three-Layer Law.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class OxdnaStatus(str, Enum):
    queued    = "queued"
    preparing = "preparing"   # writing topology/conf/input files
    running   = "running"
    failed    = "failed"
    stopped   = "stopped"     # manually stopped
    completed = "completed"   # all stages done


@dataclass
class OxdnaHealthSample:
    wall_time:             float
    stage:                 str
    bp_retained_fraction:  Optional[float] = None   # designed WC pairs still formed
    potential_energy:      Optional[float] = None   # per-particle U (oxDNA units)
    max_backbone_clash:    Optional[float] = None   # overstretched-bond proxy (steric)
    steps_per_s:           Optional[float] = None
    passed:                bool = True
    reason:                str  = ""


@dataclass
class OxdnaStageStatus:
    name:   str          # e.g. "1_mc_relax", "2_md_relax", "3_equil", "4_production"
    kind:   str          # "mc" | "md_relax" | "equil" | "production"
    steps:  int
    status: str = "pending"   # pending / running / done / failed
    started_at: Optional[float] = None   # wall time the stage began running (for ETA)
    resumed: bool = False     # this stage was resumed from its own checkpoint (relabel)


@dataclass
class OxdnaJob:
    job_id:              str
    design_name:         str
    status:              OxdnaStatus
    created_at:          float
    n_nucleotides:       int = 0
    stages:              list[OxdnaStageStatus]  = field(default_factory=list)
    current_stage_idx:   int                     = 0
    error:               Optional[str]           = None
    oxdna_pid:           Optional[int]           = None
    device:              str                     = "0"      # CUDA device index
    backend:             str                     = "CUDA"   # "CPU" | "CUDA"
    salt_concentration:  float                   = 0.5      # molar
    health_samples:      list[OxdnaHealthSample] = field(default_factory=list)
    design_source_path:  Optional[str]           = None

    # ── Paths ──────────────────────────────────────────────────────────────────

    def job_dir(self, workspace_dir: Path) -> Path:
        return workspace_dir / "oxdna_jobs" / self.job_id

    def stage_dir(self, workspace_dir: Path, stage_name: str) -> Path:
        return self.job_dir(workspace_dir) / stage_name

    # ── Persistence ────────────────────────────────────────────────────────────

    def save(self, workspace_dir: Path) -> None:
        jd = self.job_dir(workspace_dir)
        jd.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["status"] = self.status.value
        # Atomic write: the background runner thread saves job.json on every
        # state change while readers (the status-poll endpoint, the test's
        # _wait_terminal) call load() concurrently.  A plain write_text()
        # truncates-then-writes, so a reader can catch an empty/partial file and
        # hit JSONDecodeError.  Write to a temp file in the same dir, then
        # os.replace() (atomic rename on POSIX) so a reader always sees either
        # the complete old or complete new file — never a torn one.
        tmp = jd / f"job.json.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, jd / "job.json")

    @classmethod
    def load(cls, job_id: str, workspace_dir: Path) -> "OxdnaJob":
        path = workspace_dir / "oxdna_jobs" / job_id / "job.json"
        data = json.loads(path.read_text())
        data["status"] = OxdnaStatus(data["status"])
        data["stages"] = [OxdnaStageStatus(**s) for s in data.get("stages", [])]
        data["health_samples"] = [
            OxdnaHealthSample(**h) for h in data.get("health_samples", [])
        ]
        data.setdefault("design_source_path", None)
        return cls(**data)

    @classmethod
    def list_jobs(cls, workspace_dir: Path) -> list["OxdnaJob"]:
        jobs_dir = workspace_dir / "oxdna_jobs"
        if not jobs_dir.exists():
            return []
        result: list[OxdnaJob] = []
        for jdir in sorted(jobs_dir.iterdir(), key=lambda p: p.name):
            if (jdir / "job.json").exists():
                try:
                    result.append(cls.load(jdir.name, workspace_dir))
                except Exception:
                    pass
        return result

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        return data


def new_oxdna_job(
    design_name: str,
    stages: list[OxdnaStageStatus],
    *,
    n_nucleotides: int = 0,
    device: str = "0",
    backend: str = "CUDA",
    salt_concentration: float = 0.5,
    design_source_path: Optional[str] = None,
) -> OxdnaJob:
    return OxdnaJob(
        job_id             = uuid.uuid4().hex[:12],
        design_name        = design_name,
        status             = OxdnaStatus.queued,
        created_at         = time.time(),
        n_nucleotides      = n_nucleotides,
        stages             = stages,
        device             = device,
        backend            = backend,
        salt_concentration = salt_concentration,
        design_source_path = design_source_path,
    )
