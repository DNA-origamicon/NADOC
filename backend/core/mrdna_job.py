"""
mrDNA Job — persistent model for a managed local mrDNA/ARBD coarse-grained
relaxation job.

Sibling of ``oxdna_job.py``.  Jobs live in
``workspace/mrdna_jobs/{job_id}/job.json`` and survive server restarts.  A mrDNA
job runs a SINGLE coarse ARBD relaxation stage (5 bp/bead multi-resolution
model, ``fine_steps=0``): mrDNA's coarse stage begins from an energy
minimisation, so it IS the relaxation — there is no separate "relax then run"
split, hence one job / one stage / one button.

Architecture note: mrDNA output is **Physical-layer / display state only**.  A
job's relaxed positions are read back for display (deforming the NADOC model or
drawing the CG bead cloud) but are NEVER written into Design topology.  See
CLAUDE.md Three-Layer Law.
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


class MrdnaStatus(str, Enum):
    queued    = "queued"
    preparing = "preparing"   # writing the design snapshot
    running   = "running"     # ARBD simulating
    failed    = "failed"
    stopped   = "stopped"     # manually stopped
    completed = "completed"   # coarse stage done + positions extracted


@dataclass
class MrdnaStageStatus:
    name:       str          # "coarse"
    steps:      int
    status:     str = "pending"   # pending / running / done / failed
    started_at: Optional[float] = None   # wall time the stage began running (for ETA)


@dataclass
class MrdnaJob:
    job_id:              str
    design_name:         str
    status:              MrdnaStatus
    created_at:          float
    n_nucleotides:       int = 0
    coarse_steps:        int = 100_000
    # fine_steps > 0 runs the mrDNA FINE stage (2 bp/bead + orientation/twist) after
    # the coarse stage.  The fine stage is what develops loop/skip CURVATURE (a
    # twist-coupled effect); coarse-only stays straight.  0 = coarse-only (fast,
    # global shape).  See backend/core/mrdna_curvature.py.
    fine_steps:          int = 0
    output_period:       int = 10_000
    device:              str = "0"      # CUDA device index
    stages:              list[MrdnaStageStatus] = field(default_factory=list)
    error:               Optional[str] = None
    arbd_pid:            Optional[int] = None
    design_source_path:  Optional[str] = None
    # Populated on completion — surfaced in the panel + used to gate the display.
    sim_seconds:         Optional[float] = None   # wall time inside model.simulate()
    n_override:          Optional[int]   = None   # nucleotides whose position moved
    n_beads:             Optional[int]   = None   # CG beads in the coarse model
    # Out-of-date detection (design edited after the relaxation ran); shares the
    # oxDNA staleness fingerprint so an edit invalidates the relaxed display.
    design_fingerprint:  Optional[str] = None
    feature_log_position: Optional[int] = None
    # Archival parity with oxDNA jobs (job_archive is kind-generic).
    archived:            bool = False
    archive_path:        Optional[str] = None

    # ── Paths ──────────────────────────────────────────────────────────────────

    def job_dir(self, workspace_dir: Path) -> Path:
        if self.archived and self.archive_path:
            return Path(self.archive_path)
        return workspace_dir / "mrdna_jobs" / self.job_id

    # ── Persistence (atomic write — runner saves while pollers read) ────────────

    def save(self, workspace_dir: Path) -> None:
        jd = self.job_dir(workspace_dir)
        jd.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["status"] = self.status.value
        tmp = jd / f"job.json.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, jd / "job.json")

    @classmethod
    def load(cls, job_id: str, workspace_dir: Path) -> "MrdnaJob":
        from backend.core.job_archive import resolve_job_json
        path = resolve_job_json(workspace_dir, "mrdna_jobs", job_id)
        data = json.loads(path.read_text())
        data["status"] = MrdnaStatus(data["status"])
        data["stages"] = [MrdnaStageStatus(**s) for s in data.get("stages", [])]
        data.setdefault("fine_steps", 0)
        data.setdefault("design_source_path", None)
        data.setdefault("sim_seconds", None)
        data.setdefault("n_override", None)
        data.setdefault("n_beads", None)
        data.setdefault("design_fingerprint", None)
        data.setdefault("feature_log_position", None)
        data.setdefault("archived", False)
        data.setdefault("archive_path", None)
        return cls(**data)

    @classmethod
    def list_jobs(cls, workspace_dir: Path) -> list["MrdnaJob"]:
        from backend.core.job_archive import archived_job_ids
        result: list[MrdnaJob] = []
        seen: set[str] = set()
        jobs_dir = workspace_dir / "mrdna_jobs"
        if jobs_dir.exists():
            for jdir in sorted(jobs_dir.iterdir(), key=lambda p: p.name):
                if jdir.is_dir() and (jdir / "job.json").exists():
                    try:
                        result.append(cls.load(jdir.name, workspace_dir))
                        seen.add(jdir.name)
                    except Exception:
                        pass
        for jid in archived_job_ids(workspace_dir, "mrdna_jobs"):
            if jid in seen:
                continue
            try:
                result.append(cls.load(jid, workspace_dir))
            except Exception:
                pass
        return result

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        return data


def new_mrdna_job(
    design_name: str,
    *,
    coarse_steps: int = 100_000,
    fine_steps: int = 0,
    output_period: int = 10_000,
    n_nucleotides: int = 0,
    device: str = "0",
    design_source_path: Optional[str] = None,
    design_fingerprint: Optional[str] = None,
    feature_log_position: Optional[int] = None,
) -> MrdnaJob:
    stages = [MrdnaStageStatus(name="coarse", steps=coarse_steps)]
    if fine_steps > 0:
        stages.append(MrdnaStageStatus(name="fine", steps=fine_steps))
    return MrdnaJob(
        job_id             = uuid.uuid4().hex[:12],
        design_name        = design_name,
        status             = MrdnaStatus.queued,
        created_at         = time.time(),
        n_nucleotides      = n_nucleotides,
        coarse_steps       = coarse_steps,
        fine_steps         = fine_steps,
        output_period      = output_period,
        device             = device,
        stages             = stages,
        design_source_path = design_source_path,
        design_fingerprint = design_fingerprint,
        feature_log_position = feature_log_position,
    )
