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
    # False only for a non-blocking advisory failure (WC-only breach): the checkpoint
    # did not fully pass but the run was allowed to continue.  Blocking failures
    # (C1' breach / hard error) keep the default True and stop the job.
    blocking:                bool = True
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
    job_id: str
    design_name: str
    protocol: str
    status: MdStatus
    created_at: float
    package_subdir: (
        str  # relative path inside job_dir (e.g. "package/B_tube_namd_solvated")
    )
    name_stem: str  # PSF/PDB file stem (e.g. "B_tube")
    segments: list[MdSegmentStatus] = field(default_factory=list)
    current_segment_idx: int = 0
    error: Optional[str] = None
    # Structured failure category, set alongside ``error`` so the UI can offer a
    # targeted fix (e.g. "vram_oom" → the downsize/refit popup).  None = generic.
    failure_kind: Optional[str] = None
    # CreateJobRequest params captured at creation so a "refit" can rebuild the
    # job with one setting changed (e.g. add a water-shell carve). None for jobs
    # created before this was recorded.
    prep_params: Optional[dict] = None
    namd_pid: Optional[int] = None
    threads: int = 16
    devices: str = "0"
    health_samples: list[MdHealthSample] = field(default_factory=list)
    design_source_path: Optional[str] = None
    seed_oxdna_job_id: Optional[str] = (
        None  # provenance: oxDNA job whose relaxed coords seeded this run
    )
    seed_mrdna_job_id: Optional[str] = (
        None  # provenance: mrDNA fine-stage job whose relaxed coords seeded this run
    )
    # Provenance link to a prior MD job this one was derived from (a refit/retry
    # spawns a fresh job from a failed one).  Drives the indented job-list
    # hierarchy: a derived job renders nested under its parent, mirroring oxDNA.
    parent_job_id: Optional[str] = None
    # True when the user explicitly stopped the job — keeps the startup/supervisor
    # auto-resume from relaunching a deliberately-paused run.  Reset on manual start.
    user_stopped: bool = False
    # Opt-in relaxation accelerator.  When True, the runner may skip a stage's
    # remaining p50/p100 chunks once its first chunk shows an energy+WC plateau
    # (backend/core/md_cutoff.py).  Default OFF — never changes existing runs.
    early_stop_relax: bool = False
    # Out-of-date detection (mirrors OxdnaJob).  ``design_fingerprint`` is a content
    # hash of the design this run was PREPARED from (set during background prep, after
    # the seed/active design is resolved — see backend.core.oxdna_staleness); a current
    # design whose fingerprint differs is out of date.  ``feature_log_position`` records
    # the design's last-active feature-log index at prep, for display.  The exact
    # design is also saved as ``design.json`` in the job dir so a stale job can be
    # rolled back to its run state.
    design_fingerprint: Optional[str] = None
    feature_log_position: Optional[int] = None
    # Archival: heavy job folders can be moved off the workspace to an external
    # location (see backend.core.job_archive).  When archived, ``archive_path`` is
    # the absolute path of the moved folder and ``job_dir`` resolves there, so the
    # package/output readers keep working and the job entry stays in the list.
    archived: bool = False
    archive_path: Optional[str] = None
    # Remote execution (Alpine/SLURM — see backend.core.md_executor + the
    # alpine-cluster-submission plan).  ``execution_target`` is the seam: "local"
    # (default) keeps the byte-for-byte local NAMD path; "alpine" routes start/stop/
    # poll through the SlurmExecutor.  The remaining fields are populated on remote
    # submit and drive polling + result fetch; ``resources`` is the recommendation
    # dict actually used; ``slurm_state`` is the last-seen raw SLURM state (badge).
    execution_target: str = "local"
    cluster_name: Optional[str] = None
    slurm_job_id: Optional[str] = None
    slurm_state: Optional[str] = None
    remote_project_dir: Optional[str] = None
    remote_scratch_dir: Optional[str] = None
    resources: Optional[dict] = None
    # Wall-clock (epoch s) when the job was last handed to the SLURM queue (submit or
    # resume) — i.e. when it entered PENDING.  Drives the queued icon's "waiting Nm"
    # tooltip.  None for local jobs / never-submitted.
    queued_at: Optional[float] = None
    # Count of user-triggered resume-from-checkpoint submissions after SLURM
    # TIMEOUTs (walltime under-estimate).  Resume is NEVER automatic — Duo 2FA
    # requires the user present — so a timed-out job goes ``resumable`` and waits
    # for a one-click Resume (see md_executor.resume_job).
    resubmit_count: int = 0
    # True when the last remote run hit a walltime TIMEOUT and can be resumed from
    # its latest NAMD checkpoint.  Set with ``status = paused`` (not failed — a
    # timeout is expected for the short-walltime strategy).  Cleared on resume.
    resumable: bool = False
    # One entry per finished remote SLURM submission (the original + each resume),
    # so the panel's expand chevron can show the full resumption chain.  Shape:
    # {slurm_job_id, state, segment_reached, segments_total, walltime, at}.
    resume_history: list = field(default_factory=list)

    # ── Paths ──────────────────────────────────────────────────────────────────

    def job_dir(self, workspace_dir: Path) -> Path:
        if self.archived and self.archive_path:
            return Path(self.archive_path)
        return workspace_dir / "md_jobs" / self.job_id

    def package_dir(self, workspace_dir: Path) -> Path:
        return self.job_dir(workspace_dir) / self.package_subdir

    # ── Persistence ────────────────────────────────────────────────────────────

    def save(self, workspace_dir: Path) -> None:
        jd = self.job_dir(workspace_dir)
        jd.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["status"] = self.status.value
        # Atomic write (temp + rename): background preparation writes job.json
        # while the status websocket reads it every 3 s — a torn read would crash
        # the socket with a JSON decode error.
        tmp = jd / "job.json.tmp"
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(jd / "job.json")

    @classmethod
    def load(cls, job_id: str, workspace_dir: Path) -> "MdJob":
        from backend.core.job_archive import resolve_job_json
        path = resolve_job_json(workspace_dir, "md_jobs", job_id)
        data = json.loads(path.read_text())
        data["status"]   = MdStatus(data["status"])
        data["segments"] = [MdSegmentStatus(**s) for s in data.get("segments", [])]
        data["health_samples"] = [
            MdHealthSample(**h) for h in data.get("health_samples", [])
        ]
        data.setdefault("design_source_path", None)
        data.setdefault("seed_oxdna_job_id", None)
        data.setdefault("seed_mrdna_job_id", None)
        data.setdefault("parent_job_id", None)
        data.setdefault("early_stop_relax", False)
        data.setdefault("failure_kind", None)
        data.setdefault("prep_params", None)
        data.setdefault("design_fingerprint", None)
        data.setdefault("feature_log_position", None)
        data.setdefault("archived", False)
        data.setdefault("archive_path", None)
        data.setdefault("execution_target", "local")
        data.setdefault("cluster_name", None)
        data.setdefault("slurm_job_id", None)
        data.setdefault("slurm_state", None)
        data.setdefault("remote_project_dir", None)
        data.setdefault("remote_scratch_dir", None)
        data.setdefault("resources", None)
        data.setdefault("queued_at", None)
        data.setdefault("resubmit_count", 0)
        data.setdefault("resumable", False)
        data.setdefault("resume_history", [])
        return cls(**data)

    @classmethod
    def list_jobs(cls, workspace_dir: Path) -> list["MdJob"]:
        from backend.core.job_archive import archived_job_ids
        result = []
        seen: set[str] = set()
        jobs_dir = workspace_dir / "md_jobs"
        if jobs_dir.exists():
            for jdir in sorted(jobs_dir.iterdir(), key=lambda p: p.name):
                if jdir.is_dir() and (jdir / "job.json").exists():
                    try:
                        result.append(cls.load(jdir.name, workspace_dir))
                        seen.add(jdir.name)
                    except Exception:
                        pass
        # Archived jobs live outside the workspace; the index records where.
        for jid in archived_job_ids(workspace_dir, "md_jobs"):
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
    seed_mrdna_job_id: Optional[str] = None,
    parent_job_id: Optional[str] = None,
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
        seed_mrdna_job_id = seed_mrdna_job_id,
        parent_job_id  = parent_job_id,
    )
