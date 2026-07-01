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
    max_backbone_fene:     Optional[float] = None   # longest backbone bond (oxDNA units) — FENE-readiness
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
    # Auto-retry budget: when a relax stage finishes but leaves the structure NOT
    # equil-ready (a backbone bond past oxDNA's FENE cliff), the runner re-runs the
    # md_relax stage with escalated parameters (longer + smaller dt + stronger force
    # cap) up to this many times before failing the job.  ``relax_retries`` counts
    # how many escalations have been spent.  0 retries → legacy behaviour (proceed
    # straight to the capped equil).
    max_relax_retries:   int                     = 3
    relax_retries:       int                     = 0
    # Auto-recovery budget for unbiased MD sampling stages (production / field / run).
    # These run at the fast production timestep (dt=0.005); a large or floppy design
    # can go numerically unstable late in the run (a single particle's coordinates
    # explode → oxDNA aborts with "a cell contains more than _max_n_per_cell
    # particles").  When that happens the runner re-runs the SAME stage from the clean
    # relaxed seed at half the timestep, up to this many times, before failing.
    # ``production_retries`` counts how many halvings have been spent.  Keeps the fast
    # dt the default and only pays the slower, stabler timestep on designs that need it.
    max_production_retries: int                   = 2
    production_retries:     int                   = 0
    # Electric-field branches: a field run is its own job seeded from a relaxed
    # parent's structure.  ``parent_job_id`` links a field child to its relaxed
    # parent (None for a normal relaxation job); ``efield`` records the field
    # params for the list sub-item hover ({force_pN, force_oxdna, dir, n_anchored}).
    parent_job_id:       Optional[str]           = None
    efield:              Optional[dict]          = None
    # Full run conditions echoed back to the panel cards when the job is selected,
    # so clicking a job re-populates every control (Advanced / Hard surface /
    # Anchors / E-field) with exactly what the run used.  Shape per route:
    #   relax  -> {kind, backend, device, salt_concentration, mc_steps,
    #              md_relax_steps, equil_steps, min_bp_retained, surface, anchors}
    #   run    -> {kind, steps, field, surface, anchors}
    #   field  -> {kind, steps, field, anchors}
    # ``surface`` = {dir, offset_nm, stiff}|None; ``anchors`` = frontend descriptors
    # (camelCase) so the Anchors card can re-render its chips verbatim.
    run_config:          Optional[dict]          = None
    # Out-of-date detection.  ``design_fingerprint`` is a content hash of the
    # design's oxDNA-build-relevant fields at creation (see
    # ``backend.core.oxdna_staleness``); if the current design's fingerprint differs,
    # the job is stale and live/production would resolve current selections against
    # this job's frozen topology and crash.  ``feature_log_position`` is the design's
    # last-active feature-log index at creation — the point to non-destructively roll
    # the feature log back to so the job becomes runnable again (None = no log).
    design_fingerprint:  Optional[str]           = None
    feature_log_position: Optional[int]          = None
    # Archival: heavy job folders can be moved off the workspace to an external
    # location (see backend.core.job_archive).  When archived, ``archive_path`` is
    # the absolute path of the moved folder and ``job_dir`` resolves there, so every
    # consumer that reads job files through job_dir()/stage_dir() keeps working and
    # new jobs can still be chained off the archived parent.
    archived:            bool                    = False
    archive_path:        Optional[str]           = None

    # ── Paths ──────────────────────────────────────────────────────────────────

    def job_dir(self, workspace_dir: Path) -> Path:
        if self.archived and self.archive_path:
            return Path(self.archive_path)
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
        from backend.core.job_archive import resolve_job_json
        path = resolve_job_json(workspace_dir, "oxdna_jobs", job_id)
        data = json.loads(path.read_text())
        data["status"] = OxdnaStatus(data["status"])
        data["stages"] = [OxdnaStageStatus(**s) for s in data.get("stages", [])]
        data["health_samples"] = [
            OxdnaHealthSample(**h) for h in data.get("health_samples", [])
        ]
        data.setdefault("design_source_path", None)
        data.setdefault("parent_job_id", None)
        data.setdefault("efield", None)
        data.setdefault("run_config", None)
        data.setdefault("max_relax_retries", 3)
        data.setdefault("relax_retries", 0)
        data.setdefault("max_production_retries", 2)
        data.setdefault("production_retries", 0)
        data.setdefault("design_fingerprint", None)
        data.setdefault("feature_log_position", None)
        data.setdefault("archived", False)
        data.setdefault("archive_path", None)
        return cls(**data)

    @classmethod
    def list_jobs(cls, workspace_dir: Path) -> list["OxdnaJob"]:
        from backend.core.job_archive import archived_job_ids
        result: list[OxdnaJob] = []
        seen: set[str] = set()
        jobs_dir = workspace_dir / "oxdna_jobs"
        if jobs_dir.exists():
            for jdir in sorted(jobs_dir.iterdir(), key=lambda p: p.name):
                if jdir.is_dir() and (jdir / "job.json").exists():
                    try:
                        result.append(cls.load(jdir.name, workspace_dir))
                        seen.add(jdir.name)
                    except Exception:
                        pass
        # Archived jobs live outside the workspace; the index records where.
        for jid in archived_job_ids(workspace_dir, "oxdna_jobs"):
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


def new_oxdna_job(
    design_name: str,
    stages: list[OxdnaStageStatus],
    *,
    n_nucleotides: int = 0,
    device: str = "0",
    backend: str = "CUDA",
    salt_concentration: float = 0.5,
    design_source_path: Optional[str] = None,
    parent_job_id: Optional[str] = None,
    efield: Optional[dict] = None,
    run_config: Optional[dict] = None,
    max_relax_retries: int = 3,
    design_fingerprint: Optional[str] = None,
    feature_log_position: Optional[int] = None,
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
        parent_job_id      = parent_job_id,
        efield             = efield,
        run_config         = run_config,
        max_relax_retries  = max_relax_retries,
        design_fingerprint = design_fingerprint,
        feature_log_position = feature_log_position,
    )
