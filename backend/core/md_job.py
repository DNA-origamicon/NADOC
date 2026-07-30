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
    # A seeded job created by "Use as NAMD seed" whose expensive solvation is
    # DEFERRED — it sits in the list unprepared until the user sets advanced options
    # and clicks "Relax from oxDNA" (POST /md/jobs/{id}/prepare).
    draft      = "draft"
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
    # True when this chunk was never actually run: the early-stop accelerator
    # (md_cutoff) found the stage had already plateaued, so this redundant chunk
    # was marked done without executing.  status stays "done" (it counts as
    # complete for all rollups); this flag only drives a distinct timeline glyph.
    skipped: bool = False
    # Bounded count of automatic checkpoint-resumes after a self-healing
    # "periodic cell too small" fatal (NPT equilibration outgrew the patch grid).
    auto_resumes: int = 0


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
    # A pending user decision the run is PAUSED on (e.g. the GPU-resident fallback
    # gate): a serialisable payload {gate, severity, title, message, options, ...}
    # the frontend renders as a modal. Set with status=paused; cleared when resolved
    # via POST /md/jobs/{id}/gpu-decision. None = no decision outstanding.
    decision: Optional[dict] = None
    # CreateJobRequest params captured at creation so a "refit" can rebuild the
    # job with one setting changed (e.g. add a water-shell carve). None for jobs
    # created before this was recorded.
    prep_params: Optional[dict] = None
    namd_pid: Optional[int] = None
    threads: int = 16
    devices: str = "0"
    health_samples: list[MdHealthSample] = field(default_factory=list)
    # Durable record of every "periodic cell has become too small" fatal, whether it was
    # auto-resumed or refused: {segment, attempt, volume_fraction, collapsing,
    # cell_start_ang, cell_end_ang, n_samples}. These used to leave no trace — the resume
    # path cleared failure_kind and overwrote `error`, so a run that crashed four times
    # while its cell collapsed 38 % finished "completed" looking clean (exp47).
    cell_shrink_events: list[dict] = field(default_factory=list)
    # Per-NPT-stage box-trace verdict (md_cell_health.settle_report): did the cell
    # settle inside 300 ps and hold, as the Aksimentiev protocol requires?
    cell_settle_reports: list[dict] = field(default_factory=list)
    design_source_path: Optional[str] = None
    seed_oxdna_job_id: Optional[str] = (
        None  # provenance: oxDNA job whose relaxed coords seeded this run
    )
    seed_mrdna_job_id: Optional[str] = (
        None  # provenance: mrDNA fine-stage job whose relaxed coords seeded this run
    )
    seed_blade_job_id: Optional[str] = (
        None  # provenance: BLADE relax job whose relaxed all-atom coords seeded this run
    )
    # Provenance link to a prior MD job this one was derived from (a refit/retry
    # spawns a fresh job from a failed one).  Drives the indented job-list
    # hierarchy: a derived job renders nested under its parent, mirroring oxDNA.
    parent_job_id: Optional[str] = None
    # Ensemble production replica marker (see backend.core.md_ensemble).  When set,
    # this job is one of N production replicas fanned out from the parent's
    # equilibrated structure with a distinct NAMD ``seed`` — ``ensemble_seed`` is that
    # seed, ``ensemble_index`` its 0-based position.  Both None for ordinary jobs and
    # refit children; the panel uses them to label replica rows and to render the
    # parent as one collapsible ensemble item.
    ensemble_seed: Optional[int] = None
    ensemble_index: Optional[int] = None
    # Flavor of a derived (parent_job_id) child.  None for a relaxation or a refit/retry
    # child; "production" for a production run branched from a completed relaxation (or
    # from another completed production, i.e. chaining).  A production child is seeded
    # with a distinct velocity ``ensemble_seed`` so multiple productions fanned out from
    # ONE equilibrated structure are independent.  Drives the child-row label
    # ("Production N" vs. an Alpine ensemble's "Replica N") and keeps the relaxation
    # parent visible + selectable while its productions nest under it.
    run_kind: Optional[str] = None
    # True when the user explicitly stopped the job — keeps the startup/supervisor
    # auto-resume from relaunching a deliberately-paused run.  Reset on manual start.
    user_stopped: bool = False
    # Opt-in relaxation accelerator.  When True, the runner may skip a stage's
    # remaining p50/p100 chunks once its first chunk shows an energy+WC plateau
    # (backend/core/md_cutoff.py).  Default OFF — never changes existing runs.
    early_stop_relax: bool = False
    # Early-stop criterion tier for a REMOTE (Alpine) relaxation.  "B" (default) =
    # energy(+volume) plateau only, stdlib evaluator, restricted to well-restrained
    # stages.  "A" = energy AND WC base-pairing (full local parity), which needs an
    # on-node MDAnalysis health step (numpy/scipy/MDAnalysis on the compute node).
    # Ignored by the LOCAL runner (which always uses the full multi-criteria path).
    early_stop_tier: str = "B"
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
    # A Stop was requested on a remote job while the cluster session was DOWN, so the
    # scancel couldn't be issued.  The job is marked stopped locally and this defers the
    # scancel to the next reconnect (poll_remote_jobs drains it) — otherwise the SLURM
    # job keeps running and burning SUs while the UI reads "stopped".  Cleared once sent.
    pending_scancel: bool = False
    # One entry per finished remote SLURM submission (the original + each resume),
    # so the panel's expand chevron can show the full resumption chain.  Shape:
    # {slurm_job_id, state, segment_reached, segments_total, walltime, at}.
    resume_history: list = field(default_factory=list)
    # Count of consecutive supervisor passes on which a SLURM-completed remote job's
    # checkpoint restart files failed to download.  A completed job leaves the poll
    # set, so a partial/failed fetch would strand the missing restart files forever
    # (and 400 any downstream chain-stage seed).  We instead keep the job re-pollable
    # and re-fetch for a bounded number of passes; this counts them (reset to 0 on a
    # clean fetch, → failed once it hits the cap).  See md_executor.reconcile_remote_job.
    fetch_attempts: int = 0

    # ── Remote execution (RunPod — execution_target == "runpod") ───────────────
    # A rented GPU pod, not a scheduler: NADOC creates it, runs the whole segment
    # ladder as ONE detached bash script, fetches results, and DESTROYS it.  See
    # backend.core.runpod_executor + the runpod-submission plan.
    #
    # ``runpod_pod_id`` is the handle we must terminate — a pod bills from creation
    # to termination whether or not it is computing, so a lost id is a silent,
    # unbounded cost.  ``runpod_pid`` is the chain script's PID on the pod: it is the
    # ONLY reliable liveness handle, because NAMD renames its process to
    # "NAMD masterPe" and `pgrep namd3` therefore matches nothing.
    runpod_pod_id: Optional[str] = None
    runpod_pid: Optional[int] = None
    # Last heartbeat epoch written by the chain script.  A stale heartbeat on an
    # INTERRUPTIBLE pod is normal — it means the pod was reclaimed, i.e. resume, not
    # fail.  The chain script is idempotent, so resume = relaunch it.
    runpod_heartbeat: Optional[int] = None

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
        data.setdefault("cell_shrink_events", [])
        data.setdefault("cell_settle_reports", [])
        data.setdefault("design_source_path", None)
        data.setdefault("seed_oxdna_job_id", None)
        data.setdefault("seed_mrdna_job_id", None)
        data.setdefault("seed_blade_job_id", None)
        data.setdefault("parent_job_id", None)
        data.setdefault("ensemble_seed", None)
        data.setdefault("ensemble_index", None)
        data.setdefault("run_kind", None)
        data.setdefault("early_stop_relax", False)   # pre-existing jobs keep their setting
        data.setdefault("early_stop_tier", "B")
        data.setdefault("failure_kind", None)
        data.setdefault("decision", None)
        data.setdefault("prep_params", None)
        data.setdefault("design_fingerprint", None)
        data.setdefault("feature_log_position", None)
        data.setdefault("archived", False)
        data.setdefault("archive_path", None)
        data.setdefault("execution_target", "local")
        data.setdefault("cluster_name", None)
        data.setdefault("slurm_job_id", None)
        data.setdefault("pending_scancel", False)
        data.setdefault("slurm_state", None)
        data.setdefault("remote_project_dir", None)
        data.setdefault("remote_scratch_dir", None)
        data.setdefault("resources", None)
        data.setdefault("queued_at", None)
        data.setdefault("resubmit_count", 0)
        data.setdefault("resumable", False)
        data.setdefault("resume_history", [])
        data.setdefault("fetch_attempts", 0)
        data.setdefault("runpod_pod_id", None)
        data.setdefault("runpod_pid", None)
        data.setdefault("runpod_heartbeat", None)
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
    seed_blade_job_id: Optional[str] = None,
    parent_job_id: Optional[str] = None,
    ensemble_seed: Optional[int] = None,
    ensemble_index: Optional[int] = None,
    run_kind: Optional[str] = None,
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
        seed_blade_job_id = seed_blade_job_id,
        parent_job_id  = parent_job_id,
        ensemble_seed  = ensemble_seed,
        ensemble_index = ensemble_index,
        run_kind       = run_kind,
    )


def _is_production_segment_name(name: str, stage: str = "") -> bool:
    """True for an (old-style appended) production segment, by name or stage text."""
    n, s = (name or "").lower(), (stage or "").lower()
    return "production" in n or "production" in s or "_prod" in n


def segment_is_production(job: "MdJob") -> bool:
    """True when a root relaxation job has old-style production segments appended onto
    it (the pre-child-model layout) — i.e. it can be reverted to a clean relaxation."""
    if job.parent_job_id is not None or job.run_kind == "production":
        return False
    return any(_is_production_segment_name(s.name, s.stage) for s in job.segments)


def revert_appended_production(job: "MdJob", workspace_dir: Path) -> dict:
    """Peel an old-style *appended* production run back off a relaxation ``MdJob`` so it
    becomes a clean completed relaxation again (the current model spawns production as a
    separate child job — see backend.core.md_ensemble / routes_md.spawn_md_production).

    The production segments are dropped from the job + manifest and their conf/log/output
    files are **moved** (never deleted) to ``job_dir/_superseded_production/`` so nothing
    is lost irreversibly.  Idempotent and non-destructive; returns a report dict.

    Refuses to touch a production child (``run_kind == "production"``) or a derived job —
    it only reverts a root relaxation that carries appended production segments."""
    if job.parent_job_id is not None or job.run_kind == "production":
        return {"reverted": False, "reason": "not a root relaxation job"}

    pkg = job.package_dir(workspace_dir)
    manifest_path = pkg / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None

    prod_names = [s.name for s in job.segments if _is_production_segment_name(s.name, s.stage)]
    has_manifest_ext = bool(manifest and "production_extension" in manifest)
    if not prod_names and not has_manifest_ext:
        return {"reverted": False, "reason": "no appended production found"}

    # Move each production segment's artifacts to a backup folder (dot-prefixed globs so
    # a "..._p10" segment never sweeps up "..._p100" files).
    backup = job.job_dir(workspace_dir) / "_superseded_production"
    output = pkg / "output"
    moved = 0
    for name in prod_names:
        candidates = [pkg / f"{name}.conf", pkg / f"{name}.log"]
        if output.exists():
            candidates.extend(sorted(output.glob(f"{name}.*")))
        for src in candidates:
            if not src.exists():
                continue
            rel = src.relative_to(job.job_dir(workspace_dir))
            dst = backup / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.replace(dst)
            moved += 1

    # Trim the job's segment list back to relaxation.
    job.segments = [s for s in job.segments if not _is_production_segment_name(s.name, s.stage)]

    # Trim the manifest + drop the production_extension record.
    if manifest is not None:
        manifest["segments"] = [
            s for s in manifest.get("segments", [])
            if not _is_production_segment_name(s.get("name", ""), s.get("stage", ""))
        ]
        manifest.pop("production_extension", None)
        text = json.dumps(manifest, indent=2)
        manifest_path.write_text(text)
        (pkg / "nadoc_md_run.json").write_text(text)

    # Restore a clean completed-relaxation state.
    job.current_segment_idx = len(job.segments)
    job.status = MdStatus.completed
    job.user_stopped = False
    job.error = None
    job.failure_kind = None
    job.save(workspace_dir)

    return {
        "reverted": True,
        "removed_segments": prod_names,
        "moved_files": moved,
        "backup_dir": str(backup),
    }
