"""
MD Job routes — create, inspect, and control NAMD simulation jobs.

All routes are prefixed with /api (set in main.py).

Route summary
─────────────
POST  /md/jobs                      create (and prepare) a new MD job
GET   /md/jobs                      list all jobs
GET   /md/jobs/{job_id}             single job status
POST  /md/jobs/{job_id}/start       start or resume a queued/stopped job
POST  /md/jobs/{job_id}/stop        stop a running job
POST  /md/jobs/{job_id}/production  append an unrestrained production stage
DELETE /md/jobs/{job_id}            delete job and generated files
GET   /md/jobs/{job_id}/health      health.jsonl records
GET   /md/jobs/{job_id}/metrics     metrics.jsonl records
GET   /md/jobs/{job_id}/display     latest displayable NADOC MD trajectory
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from dataclasses import asdict
from pathlib import Path
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

from backend.api import state as design_state
from backend.api.assembly import _WORKSPACE_DIR
from backend.core import job_archive
from backend.core import md_chain_executor as _chain
from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus, new_job
from backend.core.md_pipeline import MdPipeline, PipelineStage, StagePlan, cross_engine_seed
from backend.core.md_presets import (DEFAULT_PRESET, FAST_SHAPE, get_preset,
                                     preset_availability, preset_catalogue)
from backend.core.md_protocols import (
    EQUILIBRIUM_AWARE_PROTOCOL,
    IMPLICIT_GBIS_PROTOCOL,
    PRODUCTION_DCD_FREQ,
    SUPPORTED_PROTOCOLS,
    SegmentSpec,
    build_production_conf,
    external_forces_block,
    namd_efield_vector,
    package_npt_allowed,
    prepare_mgh_slow_release,
    prepare_equilibrium_aware_namd,
    segments_from_manifest,
    write_hmr_psf,
)
from backend.core.md_prep_progress import (
    PrepTracker,
    build_prep_phases,
    clear_prep_progress,
    design_size_factor,
    write_prep_progress,
)
from backend.core.namd_runner import apply_user_stop, default_threads, find_gmx, find_namd, is_running, pending_early_stop, reconcile_job_status, resolve_gpu_decision, set_early_stop, start_job, stop_job
from backend.core.md_vram import (
    detect_vram_mb,
    package_solvation_profile,
    recommend_downsize,
)

logger = logging.getLogger(__name__)


router = APIRouter(tags=["md"])

# Background preparation tasks, kept referenced so the event loop doesn't GC them
# mid-run (asyncio only holds weak references to tasks).
_PREP_TASKS: set[asyncio.Task] = set()


# ── Request/response models ────────────────────────────────────────────────────

class CreateJobRequest(BaseModel):
    protocol:    str   = Field(EQUILIBRIUM_AWARE_PROTOCOL, description="Protocol preset name")
    threads:     int   = Field(default_factory=default_threads, ge=1,
                               description="NAMD +p thread count; defaults to half the logical CPUs")
    devices:     str   = Field("0", description="CUDA device IDs (e.g. '0' or '0,1')")
    autostart:   bool  = Field(False, description="Start NAMD immediately after preparation")
    salt_mode:   str   = Field("screening", description="'screening' uses validated origami screening defaults; 'custom' uses Mg/NaCl fields")
    # Advanced overrides (all optional)
    ion_conc_mM: float = Field(0.0,  ge=0.0)
    mg_conc_mM:  float = Field(12.5, ge=0.0)
    padding_nm:  float = Field(1.2,  gt=0.0)
    water_shell_nm: float = Field(
        0.0, ge=0.0,
        description="If >0, keep only water within this distance (nm) of the DNA "
                    "and drop the rest, then run NVT. Halves the atom count for "
                    "large designs so GPU-resident NAMD fits a small card. "
                    "Use ≥0.6 nm (2·shell ≥ 12 Å cutoff); 1.5 nm recommended.",
    )
    minimize_steps: int = Field(4_800, ge=100)
    declash: bool = Field(
        False,
        description="Force the declash protocol (auto-enabled anyway for designs with crossover extra bases, e.g. 2xT thymines)",
    )
    force_soft: bool = Field(
        False,
        description="Run the WHOLE ladder with the soft integrator (rigidBonds none "
                    "+ 1 fs), not just the first segment. The instability 'Fix' remedy "
                    "sets this for a model that keeps blowing up rigid-bond RATTLE.",
    )
    fast: bool = Field(
        True,
        description="Fast relaxation (DEFAULT): hydrogen-mass repartitioning + 4 fs "
                    "timestep + NAMD GPU-resident on the hard ladder (~4x NPT throughput "
                    "on a capped box). Auto-disabled for soft/declash ladders. Same "
                    "simulated ns per stage (step count halved), wall-clock ~4x shorter. "
                    "Set false (or untick in the UI) if a very large design fails the "
                    "first hard segment with a GPU out-of-memory error.",
    )
    gpu_resident: Optional[str] = Field(
        None,
        description="NAMD GPU-resident mode for this run: 'auto' (DEFAULT — decided by "
                    "solvated atom count against the measured crossover), 'on' (force it) "
                    "or 'off' (force CUDA offload). Resident keeps integration + bonded "
                    "forces on the GPU and is a LARGE-system win (3.2x at 3.14M atoms), "
                    "but a LOSS below ~100k (both paths hit the same per-step floor and "
                    "resident's setup is pure overhead — measured 0.88-0.97x at 32.5k). "
                    "'on' is still refused for GBIS and for a sparsely-filled carved cell, "
                    "where it cannot run at all.",
    )

    @field_validator("gpu_resident")
    @classmethod
    def _sanctioned_gpu_resident(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s not in ("auto", "on", "off"):
            raise ValueError("gpu_resident must be 'auto', 'on', or 'off'")
        return s

    gpu_fallback_policy: Optional[str] = Field(
        None,
        description="What to do if the fastest GPU (resident) mode can't start on this "
                    "structure: 'ask' (DEFAULT — pause and ask the user, so an unattended "
                    "run stops & notifies rather than silently slowing) or 'auto_offload' "
                    "(auto-accept the ~3x slower GPU mode). None → the NADOC_GPU_FALLBACK "
                    "env default ('ask'). Stored on the job; the UI remembers it in "
                    "localStorage.",
    )
    production_timestep_fs: float = Field(
        4.0,
        description="Integrator timestep (fs) for the PRODUCTION run: 4.0 (fast, HMR + "
                    "GPUresident — the default; needs the fast relaxation ladder), 2.0 "
                    "(rigidBonds all + GPUresident, no HMR — a manual medium path), or 1.0 "
                    "(conservative reference, rigidBonds none). Only these three are allowed; "
                    "2.0 is a deliberate manual choice, never auto-selected. See "
                    "memory/feedback_namd_4fs_production_only.md.",
    )

    @field_validator("production_timestep_fs")
    @classmethod
    def _sanctioned_production_timestep(cls, v: float) -> float:
        if v not in (1.0, 2.0, 4.0):
            raise ValueError("production_timestep_fs must be 1.0, 2.0, or 4.0")
        return float(v)
    design_source_path: Optional[str] = Field(
        None,
        description="Workspace path of the part used to create this job",
    )
    oxdna_job_id: Optional[str] = Field(
        None,
        description="If set, seed the NAMD run from this completed oxDNA job's "
                    "relaxed coordinates (its OWN design.json + latest last_conf) "
                    "instead of ideal B-DNA.",
    )
    mrdna_job_id: Optional[str] = Field(
        None,
        description="If set, seed the NAMD run from this completed FINE-stage mrDNA "
                    "job's relaxed CG structure (its OWN design.json snapshot) instead "
                    "of ideal B-DNA.  Mutually exclusive with oxdna_job_id.",
    )
    blade_job_id: Optional[str] = Field(
        None,
        description="If set, seed the NAMD run from this completed BLADE relax job's "
                    "EXACT all-atom relaxed coordinates (its OWN design.json snapshot). "
                    "Unlike the oxDNA/mrDNA seeds (reconstructed from a coarse-grained "
                    "frame), BLADE is already atomistic, so the exact conformation is fed "
                    "straight into solvation via solute_coords=. Forces full-topology "
                    "(psfgen, with hydrogens) prep. Mutually exclusive with the others.",
    )
    vacuum_job_id: Optional[str] = Field(
        None,
        description="If set, seed solvation from this completed in-vacuo ENRG-MD "
                    "pre-stage (Aksimentiev tutorial §3.2) — the tutorial's §3.3 starts "
                    "from the vacuum run's last frame, not the idealised build. Normally "
                    "set automatically by the standard preset rather than by hand.",
    )
    skip_vacuum_prestage: bool = Field(
        False,
        description="Skip the in-vacuo shape-relaxation pre-stage. It is on by default "
                    "because the published protocol runs it, but it is measurably "
                    "counter-productive below ~4 helices (a 2hb's solvation box GREW "
                    "6.8%), so the UI asks first on small designs.",
    )
    execution_target: str = Field(
        "local",
        description="'local' runs NAMD as a local subprocess (default); 'alpine' "
                    "tags the job for remote SLURM submission (submit via "
                    "/md/jobs/{id}/submit-remote once prepared + connected).",
    )
    cluster_name: Optional[str] = Field(
        None, description="Cluster profile name for remote execution (default 'alpine').",
    )
    run_dir: Optional[str] = Field(
        None,
        description="Directory to write this run into (archive-from-birth). A NAMD run "
                    "produces multi-GB trajectories; pointing it at a roomy volume (e.g. an "
                    "external Archive drive) keeps them off a full system disk. The job's "
                    "folder is created at <run_dir>/<job_id> and the app resolves it via the "
                    "archive index. None → the default workspace location.",
    )
    anchors: Optional[list] = Field(
        None,
        description="Anchor scopes (shared oxDNA/CanDo picker format: overhang / cluster "
                    "/ domain / strand / base) to hold immobile via NAMD fixedAtoms for the "
                    "whole ladder. A JOB-REQUEST annotation, never a Design edit; a selection "
                    "that resolves to nothing leaves the run unanchored.",
    )
    field: Optional[dict] = Field(
        None,
        description="Uniform electric field, shared cross-engine descriptor "
                    "{'field_pN': <force per NUCLEOTIDE, pN>, 'dir': [x,y,z]} — the same "
                    "per-nucleotide load oxDNA/LAMMPS apply per bead and CanDo applies per "
                    "duplex node. Emitted as native NAMD eFieldOn/eField (q·E, exact: a DNA "
                    "nucleotide carries -1 e). Requires >=1 anchor (an unanchored uniform "
                    "force just streams the structure). A JOB-REQUEST annotation, never a "
                    "Design edit.",
    )
    relax_preset: str = Field(
        DEFAULT_PRESET,
        description="Named relaxation protocol (backend/core/md_presets.py): "
                    "'fast_shape' (vacuum ENRG-MD), 'standard' (Aksimentiev explicit "
                    "MgCl2 + ENM ladder, the default), or 'full_physics' (solvent-first "
                    "staged release). Supplies DEFAULTS only — any field the caller sets "
                    "explicitly wins.",
    )
    early_stop_relax: bool = Field(
        True,
        description="Relaxation accelerator: skip a stage's remaining p50/p100 chunks "
                    "once its first chunk shows an energy+WC plateau (multi-criteria, "
                    "backend/core/md_cutoff.py). Never skips production/qualification "
                    "stages. ON by default; the 'full_physics' preset turns it off, "
                    "since a stage you intend to publish should not be truncated.",
    )
    early_stop_tier: str = Field(
        "B",
        description="Remote (Alpine) early-stop criterion tier. 'B' (default) = "
                    "energy(+volume) only, stdlib on-node evaluator, well-restrained "
                    "stages only. 'A' = energy AND WC base-pairing (full local parity) "
                    "via an on-node MDAnalysis health step (numpy/scipy/MDAnalysis must "
                    "be on the node python; fails safe to no-skip otherwise). Ignored "
                    "for local runs.",
    )
    draft: bool = Field(
        False,
        description="Create the job as an unprepared DRAFT (status='draft') instead of "
                    "solvating immediately. Only valid for a seeded job (oxdna/mrdna). "
                    "The 'Use as NAMD seed' button uses this so the user can set advanced "
                    "options first; the deferred solvation runs on POST /md/jobs/{id}/prepare "
                    "(the 'Relax from oxDNA' button).",
    )
    allow_catenated_seed: bool = Field(
        False,
        description="Build even when a reciprocal crossover pair's two backbones are "
                    "topologically LINKED (Gauss Lk != 0) in the seed. Off by default: "
                    "both chain ends are covalently pinned into the network, so the "
                    "entanglement survives every relaxation stage and the trajectory "
                    "measures an artefact. Recorded in manifest.json either way.",
    )


class ProductionRequest(BaseModel):
    length_ns: Optional[float] = Field(None, gt=0.0, le=100.0)
    steps: Optional[int] = Field(None, ge=100, le=50_000_000)
    autostart: bool = Field(True)
    continue_from_production: bool = Field(False)
    allow_undersized_cell: bool = Field(
        False,
        description="Run even when the package's cell is too small for the solute to "
                    "rotate freely. A relaxation package is sized for its short "
                    "restrained ladder, so a long UNRESTRAINED run in it can walk the "
                    "solute into its own periodic image and quietly corrupt the "
                    "trajectory. Off by default; set it only if you know the run is "
                    "short enough or the solute is effectively spherical.",
    )
    production_timestep_fs: Optional[float] = Field(
        None,
        description="Integrator timestep (fs) for THIS production run: 1.0, 2.0 or 4.0. "
                    "Sending it PINS the choice — if the package cannot honour it the run "
                    "fails with FAILURE_TIMESTEP_PINNED rather than quietly substituting a "
                    "different one. Omit to inherit the value baked into the package "
                    "manifest at prep time, or (absent that) the auto-derived default. "
                    "Until this existed the timestep could only be chosen when the package "
                    "was PREPARED, so changing the Advanced-card dropdown before starting "
                    "production had no effect on the run at all.",
    )

    gpu_resident: Optional[str] = Field(
        None,
        description="GPU-resident mode for THIS production run: 'auto' (size gate), 'on' "
                    "or 'off'. Omit to inherit the package's prep-time choice. Production "
                    "used to hard-code resident ON for 2/4 fs regardless of size or of the "
                    "Advanced-card dropdown.",
    )

    @field_validator("production_timestep_fs")
    @classmethod
    def _sanctioned_production_timestep(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v not in (1.0, 2.0, 4.0):
            raise ValueError("production_timestep_fs must be 1.0, 2.0, or 4.0")
        return None if v is None else float(v)

    @field_validator("gpu_resident")
    @classmethod
    def _sanctioned_prod_gpu_resident(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s not in ("auto", "on", "off"):
            raise ValueError("gpu_resident must be 'auto', 'on', or 'off'")
        return s


class JobSummary(BaseModel):
    job_id:         str
    design_name:    str
    protocol:       str
    status:         str
    created_at:     float
    n_segments:     int
    current_segment_idx: int
    error:          Optional[str]
    latest_health:  Optional[dict]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _workspace() -> Path:
    return _WORKSPACE_DIR


def _load_job(job_id: str) -> MdJob:
    try:
        return reconcile_job_status(MdJob.load(job_id, _workspace()), _workspace())
    except FileNotFoundError:
        raise HTTPException(404, f"MD job {job_id!r} not found")
    except Exception as exc:
        raise HTTPException(500, f"Failed to load job {job_id}: {exc}")


# ── Out-of-date detection (design edited after an MD job was prepared) ─────────
_MD_DERIVED_FP_CACHE: dict[str, str] = {}


def _md_snapshot_design(job: MdJob):
    """The exact design this MD job was prepared from (its frozen design.json), or
    None for a job that predates snapshot-saving.

    Production/ensemble children don't prepare their own topology — they run the parent's
    PSF/PDB — so a child that lacks its own snapshot inherits it by walking up the
    ``parent_job_id`` chain to the nearest ancestor that has one.  This is what lets a
    production run be measured against the relaxation it was seeded from."""
    from backend.core.models import Design

    ws = _workspace()
    cur = job
    seen: set[str] = set()
    while cur is not None and cur.job_id not in seen:
        seen.add(cur.job_id)
        p = cur.job_dir(ws) / "design.json"
        if p.exists():
            try:
                return Design.model_validate_json(p.read_text())
            except Exception:  # noqa: BLE001
                return None
        pid = getattr(cur, "parent_job_id", None)
        if not pid:
            break
        try:
            cur = MdJob.load(pid, ws)
        except Exception:  # noqa: BLE001
            break
    return None


def _md_job_fingerprint(job: MdJob) -> "str | None":
    if job.design_fingerprint and (job.design_fingerprint.startswith("v2:")
                                   or len(job.design_fingerprint) != 64):
        return job.design_fingerprint
    cached = _MD_DERIVED_FP_CACHE.get(job.job_id)
    if cached is not None:
        return cached
    snap = _md_snapshot_design(job)
    if snap is None:
        return None
    from backend.core.oxdna_staleness import design_build_fingerprint
    fp = design_build_fingerprint(snap)
    _MD_DERIVED_FP_CACHE[job.job_id] = fp
    return fp


def _md_job_out_of_date(job: MdJob, current_fp: "str | None") -> bool:
    from backend.core.oxdna_staleness import job_out_of_date
    return job_out_of_date(_md_job_fingerprint(job), current_fp)


def _assert_md_job_current(job: MdJob) -> None:
    """Refuse (409) running production/start on a job whose design has changed since
    it was prepared (mirrors the oxDNA guard); the frontend turns it into the roll
    popup.  Stands down for an unattended chain spawn (seeds from the job's own frozen
    state, not the loaded design — see ``md_chain_executor.in_unattended_chain_spawn``)."""
    from backend.core.md_chain_executor import in_unattended_chain_spawn
    if in_unattended_chain_spawn():
        return
    from backend.core.oxdna_staleness import (
        current_active_design_fingerprint, describe_staleness, job_out_of_date)
    if job_out_of_date(_md_job_fingerprint(job), current_active_design_fingerprint()):
        try:
            current = design_state.get_or_404()
        except Exception:  # noqa: BLE001 — staleness messaging must never 500
            current = None
        raise HTTPException(
            409, describe_staleness(_md_snapshot_design(job), current, stage="prepared"))


def _jsonl_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def _job_to_summary(job: MdJob) -> JobSummary:
    latest = job.health_samples[-1] if job.health_samples else None
    latest_dict = None
    if latest is not None:
        from dataclasses import asdict
        latest_dict = asdict(latest)
    return JobSummary(
        job_id               = job.job_id,
        design_name          = job.design_name,
        protocol             = job.protocol,
        status               = job.status.value,
        created_at           = job.created_at,
        n_segments           = len(job.segments),
        current_segment_idx  = job.current_segment_idx,
        error                = job.error,
        latest_health        = latest_dict,
    )


def _latest_display_segment(job: MdJob) -> tuple[Optional[str], Optional[Path]]:
    package_dir = job.package_dir(_workspace())
    output_dir = package_dir / "output"
    candidates = []
    if 0 <= job.current_segment_idx < len(job.segments):
        candidates.append(job.segments[job.current_segment_idx])
    candidates.extend(reversed(job.segments))

    seen: set[str] = set()
    for seg in candidates:
        if seg.name in seen:
            continue
        seen.add(seg.name)
        # Prefer the newest trajectory for this segment: a resumed segment writes
        # its continuation frames to <seg>.contN.dcd, leaving the pre-checkpoint
        # <seg>.dcd intact.  Pick whichever was written most recently.
        dcds = [
            d
            for d in (
                *output_dir.glob(f"{seg.name}.cont*.dcd"),
                output_dir / f"{seg.name}.dcd",
                package_dir / f"{seg.name}.dcd",
            )
            if d.exists() and d.stat().st_size > 0
        ]
        if dcds:
            return seg.name, max(dcds, key=lambda d: d.stat().st_mtime)
    return None, None


def _md_segment_dcds(job: MdJob) -> list[tuple[str, str, Path]]:
    """Every segment that has written a DCD, in run order → (name, stage, dcd_path).
    Picks each segment's newest trajectory file (mirrors _latest_display_segment's
    per-segment preference for continuation DCDs)."""
    package_dir = job.package_dir(_workspace())
    output_dir = package_dir / "output"
    out: list[tuple[str, str, Path]] = []
    for seg in job.segments:
        dcds = [
            d for d in (
                *output_dir.glob(f"{seg.name}.cont*.dcd"),
                output_dir / f"{seg.name}.dcd",
                package_dir / f"{seg.name}.dcd",
            )
            if d.exists() and d.stat().st_size > 0
        ]
        if dcds:
            out.append((seg.name, getattr(seg, "stage", "md") or "md",
                        max(dcds, key=lambda d: d.stat().st_mtime)))
    return out


async def _run_md_analysis(request, job_id: str, kind: str, qualname: str,
                           args: tuple, *, timeout_s: float = 180.0):
    """Run a heavy md_trajectory analysis in a killable subprocess, cancelling it if
    the client disconnects (the frontend aborts the fetch when the view is toggled
    off).  Supersedes any in-flight analysis for the same (job_id, kind)."""
    from backend.core import md_analysis_runner  # noqa: PLC0415

    task = asyncio.create_task(md_analysis_runner.run_analysis(
        job_id, kind, "backend.core.md_trajectory", qualname, args, timeout_s=timeout_s))
    try:
        while not task.done():
            if request is not None and await request.is_disconnected():
                md_analysis_runner.cancel(job_id, kind)
                task.cancel()
                break
            await asyncio.sleep(0.25)
        return await task
    except asyncio.CancelledError:
        md_analysis_runner.cancel(job_id, kind)
        raise


def _traj_stride(stride) -> int | None:
    """Normalize the `?stride=` query param to a usable frame interval, or None.

    None means "no interval" — the legacy at-most-200-frames budget — so anything
    unusable (absent, 0, negative, junk) must land back on None rather than on a
    silently different downsample.  Both trajectory routes share this so they can't
    disagree about what counts as no interval."""
    try:
        n = int(stride)
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


@router.get("/md/jobs/{job_id}/trajectory")
async def get_md_job_trajectory(
    job_id: str,
    request: Request,
    stride: int | None = None,
) -> dict:
    """Composite scrub-able NAMD trajectory (every written segment, CG/nadoc beads)
    for an animation trajectory keyframe — SAME payload shape as the oxDNA
    /trajectory endpoint ({ready, n_frames, keys, frames, markers, stages}), so the
    animation player's trajectory path is reused unchanged. Deforms the active
    design (like the live Display-MD toggle).

    ``stride`` = user-set frame INTERVAL: keep every Nth frame of each written
    segment (VMD's DCD stride).  OMITTING it keeps the legacy behaviour — at most 200
    frames total, split proportionally — which is what the animation panel's
    trajectory keyframes still rely on, so don't give it a non-None default here."""
    stride = _traj_stride(stride)
    job = _load_job(job_id)
    package_dir = job.package_dir(_workspace())
    psf = package_dir / f"{job.name_stem}.psf"
    ref = package_dir / f"{job.name_stem}.pdb"
    if not psf.exists() or not ref.exists():
        return {"ready": False, "reason": "topology/reference not found"}
    segments = _md_segment_dcds(job)
    if not segments:
        return {"ready": False, "reason": "no trajectory yet"}
    # Frozen snapshot design (job's prepared state), not the live active design —
    # see _md_traj_inputs.  Fall back to active for legacy pre-snapshot jobs.
    design = _md_snapshot_design(job) or design_state.get_or_404()
    # args is applied POSITIONALLY inside the analysis subprocess, so this tuple must
    # match md_composite_trajectory's signature: (…, design, max_frames, stride).
    # A small interval on a long run is a legitimately slow request the user opted into
    # (the panel confirms first), so give it a far longer ceiling — the route already
    # kills the subprocess when the client aborts the fetch.
    result = await _run_md_analysis(
        request, job_id, "trajectory", "md_composite_trajectory",
        (psf, segments, ref, design, 200, stride),
        timeout_s=180.0 if stride is None else 900.0)
    return {"ready": result["n_frames"] > 0, **result}


@router.get("/md/jobs/{job_id}/trajectory-meta")
async def get_md_job_trajectory_meta(
    job_id: str,
    stride: int | None = None,
) -> dict:
    """Frame count + segment markers for the NAMD composite WITHOUT reading
    coordinates (DCD header only) — sizes the trajectory-keyframe slider instantly.
    Indices match GET /md/jobs/{id}/trajectory for the SAME ``stride`` exactly.
    Also reports ``total_raw`` + per-stage ``n_raw`` (undownsampled DCD counts) so the
    panel can price a different interval without another request."""
    from backend.core.md_trajectory import md_composite_meta

    stride = _traj_stride(stride)
    job = _load_job(job_id)
    package_dir = job.package_dir(_workspace())
    if not (package_dir / f"{job.name_stem}.psf").exists():
        return {"ready": False, "reason": "topology not found"}
    segments = _md_segment_dcds(job)
    if not segments:
        return {"ready": False, "reason": "no trajectory yet"}
    result = await run_in_threadpool(md_composite_meta, segments, 200, stride)
    return {"ready": result["n_frames"] > 0, **result}


@router.get("/md/jobs/{job_id}/rmsf")
async def get_md_job_rmsf(job_id: str, request: Request) -> dict:
    """Per-nucleotide flexibility map (RMSF) over the NAMD run — the MD analogue of
    GET /oxdna/jobs/{id}/rmsf. Pools EVERY written segment (flex-map gating is "all
    segments"), Kabsch-aligns each frame to the design, and returns the per-base mean
    backbone position + base normal + RMSF. SAME payload shape as the oxDNA endpoint,
    so the frontend flexibility-map code consumes it unchanged. A confidence block
    flags short runs (autocorrelated frames → true error ≥ 1/sqrt(2N))."""
    from backend.core.oxdna_health import rmsf_confidence

    inputs = _md_traj_inputs(job_id)
    if inputs is None:
        return {"ready": False, "reason": "topology/reference or trajectory not found",
                "positions": []}
    psf, ref, segments, design = inputs
    result = await _run_md_analysis(
        request, job_id, "rmsf", "md_rmsf", (psf, segments, ref, design))
    if result.get("ready"):
        result["confidence"] = rmsf_confidence(result.get("n_frames", 0))
    return result


@router.get("/md/jobs/{job_id}/shape-source")
async def get_md_shape_source(job_id: str, request: Request) -> dict:
    """The NAMD source bundle for the cross-engine comparison card (S5/N4).

    Turns the job's trajectory into the shared ``{engine, descriptors, rmsf, shape_frame,
    field}`` bundle ``build_comparison_report`` consumes — NAMD's ABSOLUTE shape descriptors
    on the rigid dsDNA core (from the Kabsch-aligned time-mean structure) + its per-nucleotide
    trajectory RMSF.  NAMD is the GOLD-OVERRIDE engine: whenever this source is present it
    becomes the reference for every observable (see :func:`shape_metrics.reference_for`).

    Both the shape and the RMSF come from ONE ``md_rmsf`` pass (reusing the ``rmsf`` analysis
    cache the flexibility map already fills), against the job's OWN prepared design snapshot so
    the descriptors match the simulated topology, not live editor state.  Physical-layer only
    (Three-Layer Law); field emission is deferred (``field:None`` — see
    :mod:`backend.core.namd_shape_source`)."""
    from backend.api.skip_twist_tuning import core_reference_geometry
    from backend.core.namd_shape_source import build_namd_shape_source

    inputs = _md_traj_inputs(job_id)
    if inputs is None:
        return {"job_id": job_id, "ready": False,
                "reason": "topology/reference or trajectory not found"}
    psf, ref, segments, design = inputs
    result = await _run_md_analysis(
        request, job_id, "rmsf", "md_rmsf", (psf, segments, ref, design))
    if not result.get("ready") or not result.get("positions"):
        return {"job_id": job_id, "ready": False,
                "reason": result.get("reason", "no trajectory frames")}
    reference = await run_in_threadpool(core_reference_geometry, design)
    bundle = await run_in_threadpool(
        build_namd_shape_source, result["positions"], reference,
        rmsf_positions=result["positions"])
    ready = bundle["descriptors"] is not None
    return {"job_id": job_id, "ready": ready,
            "n_frames": result.get("n_frames", 0), **bundle}


class MdFramesAtomisticBody(BaseModel):
    frame_indices: list[int]
    # The frame interval the trajectory was loaded with.  A composite frame index only
    # addresses the same frame within one interval, so heavy reps MUST repeat it or the
    # atomistic view lands on a different point in the run than the beads beside it.
    stride: int | None = None
    # Coordinates only, serial-indexed, to be paired with ONE /atomistic-model fetch.
    # The per-frame atom OBJECTS are ~10x larger and are what made prebuilding a whole
    # all-atom trajectory unaffordable.
    positions_only: bool = False


class MdFramesSurfaceBody(BaseModel):
    frame_indices: list[int]
    probe_radius: float = 0.28
    grid_spacing: float = 0.20
    radius_inflate: float = 1.30
    smooth: int = 15
    stride: int | None = None


def _md_traj_inputs(job_id: str):
    """(psf, ref_pdb, segments, design) for a job's composite — shared by the MD
    trajectory + per-frame atomistic/surface routes. Returns None when the
    topology/reference or any DCD is missing."""
    job = _load_job(job_id)
    package_dir = job.package_dir(_workspace())
    psf = package_dir / f"{job.name_stem}.psf"
    ref = package_dir / f"{job.name_stem}.pdb"
    if not psf.exists() or not ref.exists():
        return None
    segments = _md_segment_dcds(job)
    if not segments:
        return None
    # Analyse against the design this job was PREPARED from (its frozen design.json),
    # not whatever is loaded in the app now — mirrors the oxDNA RMSF route.  The DCD
    # atom order is fixed to the job's topology; pairing it with a drifted/other active
    # design mis-maps P atoms and silently voids the map.  Fall back to the active
    # design only for legacy jobs that predate snapshot-saving.
    design = _md_snapshot_design(job) or design_state.get_or_404()
    return psf, ref, segments, design


@router.post("/md/jobs/{job_id}/frames-atomistic")
async def md_frames_atomistic_route(job_id: str, body: MdFramesAtomisticBody,
                                    request: Request) -> dict:
    """Per-frame DNA heavy atoms for NAMD trajectory frame indices (Phase 2b) —
    {idx: {atoms, bonds}}. The NAMD model's own atoms, rendered directly.  Indices are
    COMPOSITE (what the scrub slider shows) — pass the same `stride` the trajectory was
    loaded with, or they address other frames."""
    inputs = _md_traj_inputs(job_id)
    if inputs is None:
        return {}
    psf, ref, segments, design = inputs
    # Prebuilding a whole all-atom trajectory arrives here as ONE call with many
    # indices: the context build (PSF parse + model) is ~32 s on a 300 k-atom system
    # against ~2.8 s per extra frame, and it is paid per CALL.  Scale the timeout with
    # the batch instead of letting a legitimate prebuild hit the 180 s ceiling.
    n_req = max(1, len(body.frame_indices))
    return await _run_md_analysis(
        request, job_id, "atomistic", "md_frames_atomistic",
        (psf, segments, ref, design, body.frame_indices, 200,
         _traj_stride(body.stride), body.positions_only),
        timeout_s=min(3600.0, 180.0 + 20.0 * n_req))


@router.get("/md/jobs/{job_id}/atomistic-model")
async def md_atomistic_model_route(job_id: str, request: Request) -> dict:
    """The job's STATIC heavy-atom set ({atoms, bonds, n_serials}) — fetched once, then
    /frames-atomistic?positions_only streams coordinates against it.  Mirrors the oxDNA
    `getOxdnaAtomisticModel` contract so the display controller's validated
    topology-once + positions-per-frame path is reused unchanged for NAMD."""
    inputs = _md_traj_inputs(job_id)
    if inputs is None:
        return {"atoms": [], "bonds": []}
    psf, ref, segments, design = inputs
    return await _run_md_analysis(
        request, job_id, "atomistic-model", "md_atomistic_model",
        (psf, segments, ref, design), timeout_s=600.0)


@router.post("/md/jobs/{job_id}/frames-surface")
async def md_frames_surface_route(job_id: str, body: MdFramesSurfaceBody,
                                  request: Request) -> dict:
    """Per-frame molecular surface from the NAMD DNA heavy atoms (Phase 2b) —
    surface-batch shape {idx: {vertices, faces}}.  COMPOSITE indices, same `stride`
    rule as frames-atomistic."""
    inputs = _md_traj_inputs(job_id)
    if inputs is None:
        return {}
    psf, ref, segments, design = inputs
    return await _run_md_analysis(
        request, job_id, "surface", "md_frames_surface",
        (psf, segments, ref, design, body.frame_indices, body.probe_radius,
         body.grid_spacing, body.radius_inflate, body.smooth, 200,
         _traj_stride(body.stride)))


@router.post("/md/jobs/{job_id}/analysis/cancel")
async def md_cancel_analysis(job_id: str, kind: Optional[str] = None) -> dict:
    """Kill the in-flight trajectory/RMSF/surface analysis for this job — wired to
    the frontend toggling a view OFF, so a heavy MDAnalysis read of a live, growing
    DCD can't run away after the user stops looking at it.  ``kind`` (rmsf /
    trajectory / surface / atomistic) cancels one view; omit it to cancel all."""
    from backend.core import md_analysis_runner  # noqa: PLC0415

    return {"cancelled": md_analysis_runner.cancel(job_id, kind)}


def _production_checkpoint_warning(job: MdJob, spec: SegmentSpec, *, fallback_reason: str = "") -> str:
    warnings: list[str] = []
    if fallback_reason:
        warnings.append(fallback_reason)

    sample = next((h for h in reversed(job.health_samples) if h.segment == spec.name), None)
    if sample is None:
        warnings.append("No health metrics were recorded for this checkpoint.")
    else:
        if not sample.passed:
            warnings.append(f"Checkpoint health did not pass: {sample.reason or 'unknown reason'}.")
        if sample.c1_paired_fraction is not None and sample.c1_paired_fraction < 0.95:
            warnings.append(
                f"C1' paired fraction is {sample.c1_paired_fraction * 100:.1f}%, "
                "below the normal 95.0% production qualification target."
            )
        if sample.wc_ref_relative_fraction is not None and sample.wc_ref_relative_fraction < 0.80:
            warnings.append(
                f"WC ref-relative pairing is {sample.wc_ref_relative_fraction * 100:.1f}%, "
                "below the normal 80.0% production qualification target."
            )
    return " ".join(warnings)


def _completed_production_checkpoint(job: MdJob) -> tuple[Optional[int], Optional[SegmentSpec], str]:
    package_dir = job.package_dir(_workspace())
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.exists():
        return None, None, "manifest.json not found"
    _, specs = segments_from_manifest(manifest_path)
    done = {s.name for s in job.segments if s.status == "done"}
    output = package_dir / "output"
    for idx in range(min(len(specs), len(job.segments)) - 1, -1, -1):
        spec = specs[idx]
        stage_l = spec.stage.lower()
        name_l = spec.name.lower()
        if "production" not in stage_l and "prod" not in name_l:
            continue
        if spec.name not in done:
            continue
        has_restart = all((output / f"{spec.name}.{ext}").exists() for ext in ("coor", "vel", "xsc"))
        if not has_restart:
            continue
        return idx, spec, ""
    return None, None, "No completed production checkpoint is available to continue from."


def _production_ready_checkpoint(job: MdJob) -> tuple[Optional[int], Optional[SegmentSpec], str, str]:
    package_dir = job.package_dir(_workspace())
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.exists():
        return None, None, "manifest.json not found", ""
    _, specs = segments_from_manifest(manifest_path)
    done = {s.name for s in job.segments if s.status == "done"}
    # LAST sample per segment, not "any sample that passed".  Health is now also sampled
    # WHILE a segment runs, so one segment has many samples and a structure can degrade
    # across them: the 200 ns production read c1=0.950 (passed) at 90 ns and c1=0.850
    # (FAILED) at the end.  An `any` test would call that segment healthy and offer a
    # degraded checkpoint as production-ready.  With one sample per segment this is
    # identical to the old behaviour.
    _last_by_segment: dict[str, object] = {}
    for h in job.health_samples:
        _last_by_segment[h.segment] = h
    passed = {seg for seg, h in _last_by_segment.items() if h.passed}
    latest_restrained: SegmentSpec | None = None
    latest_restrained_idx: Optional[int] = None
    latest_unqualified: tuple[int, SegmentSpec] | None = None
    for idx in range(min(len(specs), len(job.segments)) - 1, -1, -1):
        spec = specs[idx]
        if spec.name not in done:
            continue
        if passed and spec.name not in passed:
            continue
        output = package_dir / "output"
        has_restart = all((output / f"{spec.name}.{ext}").exists() for ext in ("coor", "vel", "xsc"))
        if not has_restart:
            continue
        stage_l = spec.stage.lower()
        name_l = spec.name.lower()
        if spec.scale is not None:
            if latest_restrained is None:
                latest_restrained = spec
                latest_restrained_idx = idx
            continue
        if "production" in stage_l or "prod" in name_l:
            continue
        if "probe" in stage_l or "probe" in name_l or "qualification" in stage_l or "qual" in name_l:
            return idx, spec, "", _production_checkpoint_warning(job, spec)
        if latest_unqualified is None:
            latest_unqualified = (idx, spec)

    if job.status == MdStatus.completed and latest_unqualified is not None:
        idx, spec = latest_unqualified
        warning = _production_checkpoint_warning(
            job,
            spec,
            fallback_reason=(
                "Production is enabled from a completed relaxation checkpoint, "
                "but no unrestrained qualification/probe stage was run."
            ),
        )
        return idx, spec, "", warning

    if job.status == MdStatus.completed and latest_restrained is not None and latest_restrained_idx is not None:
        warning = _production_checkpoint_warning(
            job,
            latest_restrained,
            fallback_reason=(
                "Production is enabled from a completed relaxation checkpoint that "
                "still had ENM restraints; this is normally blocked unless explicitly allowed."
            ),
        )
        return latest_restrained_idx, latest_restrained, "", warning

    if latest_restrained is not None:
        return (
            None,
            None,
            f"Latest passing checkpoint is still restrained ({latest_restrained.stage}); "
            "run an unrestrained qualification/probe before production.",
            "",
        )
    return None, None, "No passing unrestrained qualification/probe checkpoint is available yet", ""


def _seed_production_available(job: MdJob) -> bool:
    """Always False — an oxDNA-seeded job must run the restrained NAMD relaxation
    ladder before production; it can no longer jump straight to unrestrained
    production from the seed.

    The old shortcut (minimize-then-produce, skipping the ENM ladder) blew up:
    oxDNA relaxes only the COARSE structure, and reconstructing all-atom coords
    from it leaves residual steric strain (sidechains, fresh solvent, the ~10%
    oxDNA-vs-B-DNA duplex-width mismatch).  Jumping to unrestrained 310 K NPT
    exceeded the velocity limit within ~200 steps ("atoms moving too fast").  The
    seed's value is a better *global* starting shape for the SAME restrained ladder
    (00_min ENM → k0.5 → k0.1 → k0.01 → release), which the relaxation start runs
    from the seeded solvated PDB — not skipping atomistic relaxation."""
    return False


def _conservative_production_conf(spec: SegmentSpec, name_stem: str,
                                  box: tuple[float, float, float],
                                  mgh_extrabonds: bool, *,
                                  fast: bool = False,
                                  timestep_fs: Optional[float] = None,
                                  structure_psf: Optional[str] = None,
                                  anchors_file: Optional[str] = None,
                                  field: Optional[dict] = None,
                                  n_atoms: Optional[int] = None,
                                  force_resident: Optional[bool] = None,
                                  package_dir: Optional[Path] = None) -> str:
    # Thin delegate to the shared, parameterized builder in md_protocols (the ensemble
    # path calls the same builder with a per-replica seed + start_checkpoint).  Defaults
    # here reproduce the original template byte-for-byte; timestep_fs (1/2/4) selects the
    # integrator path for the user's Advanced-card choice; anchors_file/field weave the
    # external-forces block in for anchored/E-field production runs.  n_atoms/
    # force_resident carry the GPU-resident decision (size gate + explicit override) —
    # without them production hard-coded resident ON and ignored the dropdown entirely.
    # A water-shell-carved cell has vacuum corners; running production under a barostat
    # collapses it onto the solute (see md_protocols._pressure_block).  The relax ladder
    # has always honoured this; production read nothing, so it hardcoded NPT.
    return build_production_conf(
        spec, name_stem, box, mgh_extrabonds,
        fast=fast, timestep_fs=timestep_fs, structure_psf=structure_psf,
        anchors_file=anchors_file, field=field,
        n_atoms=n_atoms, force_resident=force_resident,
        npt=package_npt_allowed(package_dir) if package_dir else True,
    )


def _seed_production_conf(spec: SegmentSpec, name_stem: str,
                         box: tuple[float, float, float],
                         mgh_extrabonds: bool, minimize_steps: int, *,
                         anchors_file: Optional[str] = None,
                         field: Optional[dict] = None) -> str:
    """Production conf that starts DIRECTLY from the oxDNA-seeded solvated
    structure (no relaxation checkpoint): minimize first to clear fresh-solvent
    clashes, assign velocities at 300 K, then run unrestrained.  Used when the
    user skips the NAMD relaxation ladder on a seeded job."""
    bx, by, bz = box
    cx, cy, cz = bx / 2, by / 2, bz / 2
    extras = "extraBonds         on\nextraBondsFile     mgh_extrabonds.txt\n" if mgh_extrabonds else ""
    ext_forces = external_forces_block(anchors_file, field)
    return f"""\
structure          {name_stem}.psf
coordinates        {name_stem}.pdb

seed               54321
paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
{extras}
cellBasisVector1   {bx:.3f}  0.000    0.000
cellBasisVector2   0.000    {by:.3f}  0.000
cellBasisVector3   0.000    0.000    {bz:.3f}
cellOrigin         {cx:.3f}   {cy:.3f}   {cz:.3f}

wrapAll            on
wrapWater          on
exclude            scaled1-4
oneFourScaling     1.0
switching          on
switchdist         10.0
cutoff             12.0
pairlistdist       14.0
PME                yes
PMEGridSpacing     1.0
rigidBonds         none
rigidTolerance     1.0e-8
timestep           1.0
nonbondedFreq      1
fullElectFrequency 1
stepspercycle      10
langevin           on
langevinTemp       300
langevinDamping    5
langevinHydrogen   off
useGroupPressure   yes
useFlexibleCell    no
useConstantArea    no
langevinPiston     on
langevinPistonTarget  1.01325
langevinPistonPeriod  200.0
langevinPistonDecay   100.0
langevinPistonTemp 300
outputEnergies     100
xstFreq            1000
restartfreq        1000
binaryrestart      yes
constraints        off
{ext_forces}outputName         output/{spec.name}
dcdFile            output/{spec.name}.dcd
dcdFreq            {spec.dcd_freq}
xstFile            output/{spec.name}.xst
temperature        300
minimize           {minimize_steps}
reinitvels         300
run                {spec.steps}
"""


def _production_steps_and_ns(body: ProductionRequest, timestep_fs: float) -> tuple[int, float]:
    """Convert a production request into (integration steps, simulated ns).

    ``steps`` is a raw integration-step count (timestep-independent); ``length_ns``
    is a wall of simulated time, so the step count needed to reach it scales
    inversely with the timestep — the whole point of the 4 fs fast path is fewer
    steps for the same ns."""
    if body.steps is not None:
        steps = max(100, int(body.steps))
        return steps, steps * timestep_fs / 1_000_000.0
    length_ns = body.length_ns if body.length_ns is not None else 1.0
    steps = max(100, int(round(length_ns * 1_000_000.0 / timestep_fs)))
    return steps, length_ns


def _production_fast_plan(job: MdJob, body: ProductionRequest) -> dict:
    """Resolve the production timestep, step count, and fast-mode eligibility.

    A user can pick the production timestep by hand in the Advanced card (1/2/4 fs),
    stored as ``manifest["production_timestep_fs"]``.  When present it wins; otherwise
    (older packages) the timestep is auto-derived: HMR/4fs when the relaxation ladder
    itself validated 4 fs rigid dynamics for THIS design (``fast_relaxation.enabled``)
    and it is not a declash design (residual single-stranded contacts that crash
    rigidBonds RATTLE), else the 1 fs conservative reference.

    ``fast`` here means the 4 fs HMR + GPUresident path (needs the HMR PSF built in
    ``_append_production_segments``).  2 fs is GPUresident but non-HMR; 1 fs is the
    conservative reference.  Note a NORMAL fast ladder always carries ONE soft
    strain-relief segment, so "any soft segment" is the wrong eligibility signal."""
    package_dir = job.package_dir(_workspace())
    try:
        manifest = json.loads((package_dir / "manifest.json").read_text())
    except (OSError, ValueError):
        manifest = {}
    relaxed_fast = bool(manifest.get("fast_relaxation", {}).get("enabled"))
    declash = bool(manifest.get("declash"))
    # Precedence: THIS request's dt (the panel's dropdown, chosen at production time) >
    # the value baked into the manifest when the package was PREPARED > the auto default.
    # The request level exists because the dropdown used to reach prep only: changing it
    # before pressing Start Production had no effect on the run, so a user could select
    # 2 fs, watch a "2 fs" estimate, and get a 1 fs trajectory.
    requested = body.production_timestep_fs
    if requested not in (1.0, 2.0, 4.0):
        requested = manifest.get("production_timestep_fs")
    pinned = requested in (1.0, 2.0, 4.0)
    if pinned:
        timestep_fs = float(requested)
    else:
        timestep_fs = 4.0 if (relaxed_fast and not declash) else 1.0
    # `fast` means "the 4 fs HMR path", nothing more.  It used to be
    # `(timestep_fs == 4.0) and not declash`, which is the SAME relax-constrains-production
    # coupling as the removed conflict, just expressed through a different variable: with
    # declash it went False, the replica builder read that as "no HMR", and a requested 4 fs
    # came out as a silent 1 fs run at ~80 ns/day.  The HMR PSF is built on demand now, so
    # the relaxation protocol has no say here.
    fast = (timestep_fs == 4.0)
    #
    # This used to silently rewrite timestep_fs to 1.0 — including when the user had
    # PINNED 4 fs in the Advanced card.  The card then displayed 4 fs while the run
    # executed at 1 fs: a 4x step-count difference the user never agreed to and had no
    # way to see.  Measured consequence on 2hb_1xT: a "4 fs" 25 ns production ran 25M
    # 1 fs steps.  Note the card's existing warning keys off the FAST checkbox, and
    # `declash` auto-enables from extra bases independently of it, so that warning does
    # not fire for this case either — the downgrade was completely invisible.
    #
    # Now: an AUTO-derived 4 fs still falls back quietly (nothing was promised), but a
    # PINNED one is a hard conflict.  The caller turns it into a failed job carrying
    # FAILURE_TIMESTEP_PINNED, so the UI surfaces "NAMD run ended prematurely" with the
    # reason instead of quietly producing a different trajectory.
    # The relaxation's integrator does NOT constrain production's.
    #
    # A ladder exists to produce equilibrated COORDINATES; once it has, the user is free to
    # produce from them at any sanctioned timestep.  An earlier version refused 2/4 fs on a
    # declash package outright, on two premises that do not survive contact:
    #   * "no HMR PSF" — production BUILDS one on demand from the package's own PSF
    #     (write_hmr_psf, see _append_production_segments); it was never a prerequisite,
    #     only an artefact the fast ladder happened to leave behind.
    #   * "residual single-stranded contacts crash RATTLE" — that describes the STARTING
    #     structure, which is precisely what the ladder removed.  Measured: a rigidBonds-all
    #     2 fs production off a declash relax ran 412k steps with no RATTLE failure.
    # So there is no conflict to raise here.  4 fs on an extra-base design can still hit the
    # Fix-B problem (HMR lightens C5' on unpaired inserts), but that is an empirical
    # stability question the run answers — and the instability rescue already handles it —
    # not grounds to forbid the attempt.  Warn, never block.
    warning = None
    if declash and timestep_fs == 4.0:
        warning = (
            "4 fs production on a declash package (crossover extra bases / extensions): the "
            "HMR PSF is being built from the relaxed structure, but hydrogen-mass "
            "repartitioning lightens C5' on UNPAIRED inserted bases, which can fail RATTLE "
            "at 4 fs. Watch the first frames; if it blows up, the geometric + Fix B prep "
            "(heavy extra bases) is the fix — see project_extra_base_4fs_geometric_fixb."
        )
    # GPU-resident for production: this request's choice > the package's prep-time mode >
    # "auto" (the atom-count gate inside build_production_conf).  None here means auto.
    resident_mode = (body.gpu_resident
                     or manifest.get("gpu_resident_mode")
                     or "auto")
    force_resident = {"on": True, "off": False}.get(str(resident_mode).lower())
    total_steps, length_ns = _production_steps_and_ns(body, timestep_fs)
    return {
        "total_steps": total_steps,
        "length_ns": length_ns,
        "timestep_fs": timestep_fs,
        "fast": fast,
        "timestep_warning": warning,
        "force_resident": force_resident,
    }


def _append_production_segments(
    job: MdJob,
    plan: dict,
    *,
    continue_from_production: bool = False,
) -> list[SegmentSpec]:
    total_steps = plan["total_steps"]
    from_seed = False
    if continue_from_production:
        checkpoint_idx, checkpoint, reason = _completed_production_checkpoint(job)
        warning = ""
        if checkpoint is None:
            raise HTTPException(400, reason)
        checkpoint_name = checkpoint.name
    else:
        checkpoint_idx, checkpoint, reason, warning = _production_ready_checkpoint(job)
        if checkpoint is None:
            # No relaxation checkpoint — but an oxDNA-seeded job can produce
            # directly from its relaxed solvated structure (minimize-then-produce).
            if _seed_production_available(job):
                from_seed = True
                checkpoint_name = "oxdna_seed"
                warning = ("NAMD relaxation skipped: the oxDNA-seeded structure is "
                           "minimized then produced unrestrained. Watch the first frames.")
            else:
                raise HTTPException(400, reason)
        else:
            checkpoint_name = checkpoint.name
    package_dir = job.package_dir(_workspace())
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    name_stem = manifest["name_stem"]
    box = tuple(float(x) for x in manifest["box_ang"])
    mgh_extrabonds = bool(manifest.get("mgh_extrabonds"))
    min_steps = int(manifest.get("minimization", {}).get("steps", 4800) or 4800)

    # Production integrator timestep comes from the plan (user's Advanced-card choice:
    # 4/2/1 fs, or the auto default).  A from-seed job (reconstructed, unequilibrated
    # coords) always runs the 1 fs conservative path regardless of the request.
    timestep_fs = float(plan.get("timestep_fs") or (4.0 if plan.get("fast") else 1.0))
    if from_seed:
        timestep_fs = 1.0
    # 4 fs (HMR + GPUresident + rigidBonds all) needs the HMR PSF (non-water H x3) so
    # rigidBonds all stays stable at 4 fs.  A fast relaxation ladder already wrote
    # {stem}_hmr.psf; otherwise build it once here.  2 fs (rigidBonds all, GPUresident,
    # standard masses) and 1 fs (conservative reference) use the plain PSF — no HMR.
    fast = (timestep_fs == 4.0)
    structure_psf: Optional[str] = None
    n_hmr = 0
    if fast:
        src_psf = package_dir / f"{name_stem}.psf"
        hmr_psf = package_dir / f"{name_stem}_hmr.psf"
        if src_psf.exists():
            if not hmr_psf.exists():
                n_hmr = write_hmr_psf(src_psf, hmr_psf)
            structure_psf = hmr_psf.name
        else:                       # no PSF to repartition — fall back to safe path
            fast, timestep_fs = False, 1.0

    # Anchors + E-field are properties of the JOB, recorded at prep; an extended
    # production stage must run under the same ones (a field job whose production stage
    # silently lost its anchors would just drift the structure across the box).
    anchors_file = (manifest.get("files") or {}).get("anchors")
    field = manifest.get("field") or None

    existing = {s["name"] for s in manifest.get("segments", [])}
    stage_idx = len({s["stage"] for s in manifest.get("segments", [])}) + 1
    length_ns = total_steps * timestep_fs / 1_000_000.0
    label_ns = f"{length_ns:g}".replace(".", "p")
    previous = "" if from_seed else checkpoint.name
    segments: list[SegmentSpec] = []
    for pct, frac in ((10.0, 0.10), (50.0, 0.40), (100.0, 0.50)):
        steps = max(100, int(round(total_steps * frac)))
        name = f"{name_stem}_{stage_idx:02d}_production_{label_ns}ns_k0_p{int(pct)}"
        if name in existing:
            previous = name
            continue
        stage_label = {4.0: "fast", 2.0: "medium", 1.0: "conservative"}.get(timestep_fs, "conservative")
        spec = SegmentSpec(
            name=name,
            stage=f"{length_ns:g} ns {stage_label} production run",
            percent=pct,
            steps=steps,
            temp=300.0,
            damping=5.0,
            scale=None,
            npt=True,
            previous=previous,
            reinit=False,
            dcd_freq=PRODUCTION_DCD_FREQ,
            min_c1_paired=0.90,
            min_wc_ref_relative=0.25,
        )
        # The FIRST from-seed segment starts from the solvated PDB (minimize +
        # heat); every later split-segment continues from the prior restart.
        if from_seed and not previous:
            conf = _seed_production_conf(spec, name_stem, box, mgh_extrabonds, min_steps,
                                         anchors_file=anchors_file, field=field)
        else:
            conf = _conservative_production_conf(
                spec, name_stem, box, mgh_extrabonds,
                fast=fast, timestep_fs=timestep_fs, structure_psf=structure_psf,
                anchors_file=anchors_file, field=field,
                n_atoms=_psf_atom_count(package_dir / f"{name_stem}.psf") or None,
                force_resident=plan.get("force_resident"),
                package_dir=package_dir,
            )
        (package_dir / f"{spec.name}.conf").write_text(conf)
        segments.append(spec)
        previous = name

    if not segments:
        raise HTTPException(400, "A production stage with this length already exists")

    start_idx = len(manifest["segments"])
    manifest["segments"].extend(asdict(s) for s in segments)
    manifest["production_extension"] = {
        "length_ns": length_ns,
        "steps": total_steps,
        "previous": checkpoint_name,
        "from_seed": from_seed,
        "continue_from_production": continue_from_production,
        "first_new_segment": segments[0].name,
        "last_new_segment": segments[-1].name,
        "timestep_fs": timestep_fs,
        "settings": {
            4.0: "fast_hmr_gpuresident_4fs",
            2.0: "medium_gpuresident_2fs",
            1.0: "conservative_unrestrained",
        }.get(timestep_fs, "conservative_unrestrained"),
        "fast_production": {
            "enabled": fast,
            "hydrogens_repartitioned": n_hmr,
            "structure_psf": structure_psf,
            # 2 fs is GPUresident (rigidBonds all) without HMR; only 4 fs uses HMR.
            "gpu_resident": timestep_fs in (2.0, 4.0),
            "timestep_fs": timestep_fs,
            "note": "HMR (non-water H x3) + GPUresident + 4 fs; production "
                    "electrostatics unchanged from the conservative path — "
                    "integrator/throughput knobs only (~10x, 1.3 -> >16 ns/day).",
        },
        "health_gate": {"min_c1_paired": 0.90, "min_wc_ref_relative": 0.25},
        "advisory_gate": {"wc_ref_relative": 0.75},
        "warning": warning,
    }
    text = json.dumps(manifest, indent=2)
    manifest_path.write_text(text)
    (package_dir / "nadoc_md_run.json").write_text(text)

    job.segments.extend(
        MdSegmentStatus(
            name=s.name,
            stage=s.stage,
            percent=s.percent,
            steps=s.steps,
            status="pending",
        )
        for s in segments
    )
    job.current_segment_idx = start_idx
    job.status = MdStatus.queued
    job.error = None
    job.user_stopped = False  # new work to do — allow auto-resume again
    job.save(_workspace())
    return segments


# ── Routes ─────────────────────────────────────────────────────────────────────

def _sequenced_base_count(design) -> int:
    return sum(
        sum(1 for c in (s.sequence or "") if c.upper() in "ACGT")
        for s in design.strands
    )


_NO_SEQUENCE_MSG = (
    "Design has no sequence assigned — every nucleotide would be written as "
    "thymine (THY), making the topology physically meaningless. "
    "Assign a scaffold sequence (e.g. M13mp18) and staple sequences before "
    "starting an MD run."
)


@router.get("/md/relax-presets")
async def list_relax_presets() -> dict:
    """The named relaxation protocols the panel offers, cheapest first.

    Each entry carries its label, a one-paragraph summary, the settings it defaults, its
    literature reference, and whether it is runnable — the vacuum tier is listed but
    marked unavailable rather than silently missing, so the menu tells the truth about
    what this build can do.
    """
    return {"presets": preset_catalogue(), "default": DEFAULT_PRESET}


def _apply_relax_preset(body: CreateJobRequest) -> CreateJobRequest:
    """Fill unset request fields from the chosen preset; DERIVE ``protocol`` from it.

    ``model_fields_set`` is exactly "what the caller actually sent", so a preset supplies
    defaults without ever overriding an explicit choice — except for ``protocol``, which
    the preset OWNS.  The panel used to carry a second protocol dropdown, so you could
    ask for "Standard (Aksimentiev)" (explicit MgCl2 + CUFIX) while separately selecting
    implicit solvent, and nothing caught it.

    Backward compatibility for API callers, which the panel no longer exercises:

    * ``protocol`` alone, no ``relax_preset`` → honoured as before (legacy path);
    * both, and they agree → fine;
    * both, and they disagree → 400 rather than a silent override.
    """
    explicit = set(body.model_fields_set)
    preset_id = getattr(body, "relax_preset", None)
    preset = get_preset(preset_id)
    wanted = preset.defaults.get("protocol")

    if "protocol" in explicit and wanted and body.protocol != wanted:
        if "relax_preset" not in explicit:
            return body                      # legacy caller: protocol alone still rules
        raise HTTPException(
            400,
            f"protocol={body.protocol!r} contradicts relax_preset={preset.id!r}, which "
            f"runs {wanted!r}. Protocol is derived from the preset — send one or the "
            f"other.")

    if not preset.defaults:
        return body
    updates = {k: v for k, v in preset.defaults.items()
               if k in type(body).model_fields and (k == "protocol" or k not in explicit)}
    return body.model_copy(update=updates) if updates else body


@router.post("/md/jobs")
async def create_md_job(body: CreateJobRequest) -> dict:
    """Create a new MD job and prepare it (solvation + config gen) in the background.

    Returns immediately with status=``preparing`` and a ``job_id``.  The caller
    subscribes to ``/ws/md-jobs/{job_id}`` to watch a live, ETA-bearing progress
    bar (the ``prep_progress`` field) while solvation runs, and to learn whether
    prep ended in ``queued`` (success) or ``failed``.  Previously this endpoint
    blocked for the whole 60-120 s+ preparation, so the UI could only show an
    indeterminate spinner with no ETA and no way to detect a hung run.
    """
    preset = get_preset(body.relax_preset)
    # Host-aware, not just build-aware: GBIS needs a non-CUDA NAMD binary, and finding
    # that out AFTER solvation (which is what happened) wastes a prep and looks like a
    # crash rather than an unmet requirement.
    _ok, _why = preset_availability(preset)
    if not _ok:
        raise HTTPException(
            400, f"The {preset.label!r} preset cannot run here. {_why}")
    # Preset supplies defaults for anything the caller did not set explicitly.
    body = _apply_relax_preset(body)

    if body.protocol not in SUPPORTED_PROTOCOLS:
        raise HTTPException(400, f"Unknown protocol: {body.protocol!r}")
    if body.salt_mode not in {"screening", "custom"}:
        raise HTTPException(400, f"Unknown salt_mode: {body.salt_mode!r}")

    # E-field guards.  Both are physics/engine facts, not preferences, so they belong
    # here rather than only in the UI.  `field` is an untyped dict (mirroring CanDo's), so
    # a malformed one must become a 400, not a 500 from float()/unpacking.
    try:
        _has_field = namd_efield_vector(body.field) is not None
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            400, f"Malformed field spec (expected {{'field_pN': <pN>, 'dir': [x,y,z]}}): {exc}")
    if _has_field:
        # A uniform force on every nucleotide is a net force on the centre of mass: an
        # unanchored structure just streams across the box instead of deflecting.  Anchors
        # are recommended but no longer required — the UI warns; the run is not blocked.
        if "," in (body.devices or ""):
            # NAMD 3: "EField is not compatible with multi-GPU GPUresident".
            raise HTTPException(
                400, "NAMD cannot combine an electric field with a multi-GPU run. "
                     "Use a single device (e.g. devices='0').")

    # Engine availability is cheap — fail fast (synchronously) so the user gets a
    # 400 instead of a job that immediately fails in the background.
    try:
        logger.info("create_md_job: NAMD=%s", find_namd())
        logger.info("create_md_job: GROMACS=%s", find_gmx())
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))

    if sum(bool(x) for x in (body.oxdna_job_id, body.mrdna_job_id, body.blade_job_id)) > 1:
        raise HTTPException(400, "Seed from ONE of oxDNA / mrDNA / BLADE, not several.")
    # A BLADE seed carries the exact all-atom conformation via solute_coords, which only
    # lines up under the full psfgen topology (with hydrogens); GBIS is itself implicit
    # solvent and re-solvating a BLADE-implicit relax under GBIS defeats the purpose.
    if body.blade_job_id and body.protocol == IMPLICIT_GBIS_PROTOCOL:
        raise HTTPException(
            400, "A BLADE seed feeds an EXPLICIT-solvent NAMD run — the implicit-GBIS "
                 "protocol re-solvates implicitly and cannot use the exact all-atom seed. "
                 "Choose an explicit-solvent protocol.")
    if body.vacuum_job_id and body.protocol == IMPLICIT_GBIS_PROTOCOL:
        raise HTTPException(
            400, "A vacuum pre-stage seeds an EXPLICIT-solvent run; the implicit-GBIS "
                 "protocol has no solvation step to seed.")
    seeded = bool(body.oxdna_job_id or body.mrdna_job_id or body.blade_job_id)
    if body.draft and not seeded:
        raise HTTPException(400, "A draft job must be seeded from an oxDNA / mrDNA / BLADE job.")
    if seeded:
        # The seed's design lives on disk (the source job's snapshot); it is resolved in
        # the background worker so its (slow) reconstruction shows on the progress
        # bar.  A cheap up-front existence check still rejects a bad job id with a
        # fast 400 before any work is queued.
        try:
            if body.oxdna_job_id:
                from backend.core.oxdna_runner import assert_namd_seed_available  # noqa: PLC0415
                await run_in_threadpool(assert_namd_seed_available, body.oxdna_job_id, _workspace())
            elif body.mrdna_job_id:
                from backend.core.mrdna_runner import assert_mrdna_namd_seed_available  # noqa: PLC0415
                await run_in_threadpool(assert_mrdna_namd_seed_available, body.mrdna_job_id, _workspace())
            else:
                from backend.core.blade_runner import assert_blade_namd_seed_available  # noqa: PLC0415
                await run_in_threadpool(assert_blade_namd_seed_available, body.blade_job_id, _workspace())
        except FileNotFoundError as exc:
            # A seed is named deliberately ("Use as NAMD seed"), so an unusable one is a
            # real error rather than something to quietly relax without.
            raise HTTPException(400, str(exc))
        design = None
        name = _seed_design_name(body)   # nice list label; provisional otherwise
        size_factor = 1.0
    else:
        # The active design is request-scoped (doc session contextvar), so it must
        # be captured here on the request thread, not in the background worker.
        design = design_state.get_or_404()
        if _sequenced_base_count(design) == 0:
            raise HTTPException(400, _NO_SEQUENCE_MSG)
        # Scaffold-specific: sequenced STAPLES with a None SCAFFOLD slip past the
        # count check above but still build as poly-T (the 6hbx100_90deg incident).
        # Block up front so the user gets an immediate, actionable message rather than
        # a job that spawns "preparing" then dies in background prep.  The build-time
        # guard in prepare_mgh_slow_release stays as the backstop for seeded/RunPod paths.
        from backend.core.md_sequence_guard import require_sequenced_scaffold  # noqa: PLC0415
        try:
            require_sequenced_scaffold(design)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        name = (design.metadata.name or "design").replace(" ", "_")
        size_factor = design_size_factor(design)

    # Draft: record the seed + provenance now, DEFER solvation.  The job appears in
    # the list as 'draft' and is prepared+started later via POST /md/jobs/{id}/prepare
    # ("Relax from oxDNA"), so the user can set advanced options first.
    if body.draft:
        job = _spawn_draft_job(body, name=name)
        return job.to_dict()

    # The published protocol relaxes SHAPE in vacuum before solvating (tutorial §3.2),
    # and §3.3 starts from that run's last frame.  When it applies, this call creates the
    # VACUUM job and stores the caller's request on it; the supervisor spawns the solvated
    # run from the relaxed coordinates once the vacuum stage completes.
    if _wants_vacuum_prestage(body, design):
        return _spawn_vacuum_prestage(body, design=design, name=name).to_dict()

    job = _spawn_prep_job(body, design=design, seeded=seeded, name=name, size_factor=size_factor)
    return job.to_dict()


@router.post("/md/jobs/{job_id}/prepare")
async def prepare_draft_job(job_id: str, body: CreateJobRequest) -> dict:
    """Prepare (solvate) a DRAFT job with the given advanced settings, then start it.

    Backs the "Relax from oxDNA" button: a draft created by "Use as NAMD seed"
    deferred its solvation so the user could set options.  This runs the STANDARD
    prep pipeline into the SAME job id, seeding from the draft's recorded oxDNA/mrDNA
    source (the body's seed ids are ignored — the draft owns the seed).  ``autostart``
    (in the body) launches the run once prep finishes, exactly like a normal relax.
    """
    job = _load_job(job_id)
    if job.status != MdStatus.draft:
        raise HTTPException(400, "Job is not a draft (already prepared).")

    try:
        find_namd(); find_gmx()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))

    # The draft owns the seed; the body only carries user-adjusted advanced settings.
    params = body.model_dump()
    params["oxdna_job_id"] = job.seed_oxdna_job_id
    params["mrdna_job_id"] = job.seed_mrdna_job_id
    params["blade_job_id"] = job.seed_blade_job_id
    params["draft"] = False
    params.setdefault("design_source_path", job.design_source_path)
    new_body = CreateJobRequest(**params)

    seeded = bool(new_body.oxdna_job_id or new_body.mrdna_job_id or new_body.blade_job_id)
    if not seeded:
        raise HTTPException(400, "Draft has no seed source; cannot prepare.")
    try:
        if new_body.oxdna_job_id:
            from backend.core.oxdna_runner import assert_namd_seed_available  # noqa: PLC0415
            await run_in_threadpool(assert_namd_seed_available, new_body.oxdna_job_id, _workspace())
        elif new_body.mrdna_job_id:
            from backend.core.mrdna_runner import assert_mrdna_namd_seed_available  # noqa: PLC0415
            await run_in_threadpool(assert_mrdna_namd_seed_available, new_body.mrdna_job_id, _workspace())
        else:
            from backend.core.blade_runner import assert_blade_namd_seed_available  # noqa: PLC0415
            await run_in_threadpool(assert_blade_namd_seed_available, new_body.blade_job_id, _workspace())
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc))

    _spawn_prep_job(new_body, design=None, seeded=True, name=job.design_name or "design",
                    size_factor=1.0, existing_job=job)
    logger.info("prepare draft %s (seed_oxdna=%s seed_mrdna=%s seed_blade=%s autostart=%s)",
                job_id, job.seed_oxdna_job_id, job.seed_mrdna_job_id, job.seed_blade_job_id,
                new_body.autostart)
    return MdJob.load(job_id, _workspace()).to_dict()


@router.post("/md/jobs/estimate-disk")
async def estimate_md_disk(body: CreateJobRequest) -> dict:
    """Forecast the disk a relaxation run would write vs. free space.

    The panel calls this before ``POST /md/jobs`` so it can pop a Continue/Cancel
    warning when finishing the run would leave the disk below the 10 GB floor.
    Best-effort: an oxDNA-seeded job (design resolved later) or any estimation
    error returns ``warn=False`` so the launch is never blocked by the forecast.
    """
    from backend.core.disk_guard import forecast, namd_run_output_bytes
    from backend.core.md_protocols import design_has_extra_bases, mgh_slow_release_segments
    from backend.core.md_vram import estimate_profile_from_design

    if body.oxdna_job_id or body.mrdna_job_id or body.blade_job_id:
        # A seeded job's design is resolved later from the source job's snapshot, not the
        # live design — so we can't forecast here; never block the launch on it.
        return {**forecast(_workspace(), 0), "skipped": True}
    try:
        design = design_state.get_or_404()
        profile = await run_in_threadpool(
            estimate_profile_from_design, design, padding_nm=body.padding_nm)
        if not profile:
            return {**forecast(_workspace(), 0), "skipped": True}
        n_atoms = profile["dna_atoms"] + profile["full_water"] * 3 + profile["ion_atoms"]
        soft = body.declash or body.force_soft or design_has_extra_bases(design)
        timestep_fs = 4.0 if (body.fast and not soft) else 2.0
        _, segments = mgh_slow_release_segments("est", timestep_fs=timestep_fs)
        predicted = namd_run_output_bytes(segments, n_atoms)
    except Exception as exc:  # noqa: BLE001 — a forecast must never block a launch
        logger.warning("estimate_md_disk failed (allowing launch): %s", exc)
        return {**forecast(_workspace(), 0), "skipped": True}
    return forecast(_workspace(), predicted)


@router.post("/md/jobs/preflight-vram")
async def preflight_md_vram(body: CreateJobRequest) -> dict:
    """Pre-flight water-box SIZE verdict for a Relax launch, before any build (Gate A).

    The panel calls this before ``POST /md/jobs`` (when the water shell is on auto) so it
    can show the size gate: A1 (auto-fit a comfortable shell), A2 (only a tight shell
    fits — ask), A3 (too large for this GPU — stop). Returns the ``recommend_downsize``
    advice + ``tier``. Best-effort: a seeded job (design resolved later, at prep) or any
    error returns ``{skipped:true, tier:"ok"}`` so the launch is never blocked.
    """
    from backend.core.md_vram import preflight_vram_advice

    if body.oxdna_job_id or body.mrdna_job_id or body.blade_job_id:
        # Seeded job: the atomistic model is resolved later from the source job's
        # snapshot, so pre-flight can't size it — prep's auto_water_shell still carves.
        return {"skipped": True, "tier": "ok"}
    try:
        design = design_state.get_or_404()
        return await run_in_threadpool(
            preflight_vram_advice, design, padding_nm=body.padding_nm, devices=body.devices)
    except Exception as exc:  # noqa: BLE001 — a preflight must never block a launch
        logger.warning("preflight_md_vram failed (allowing launch): %s", exc)
        return {"skipped": True, "tier": "ok"}


def _psf_atom_count(psf_path: Path) -> int:
    """Total atom count from a PSF ``!NATOM`` header (0 if unreadable)."""
    if not psf_path.exists():
        return 0
    try:
        with psf_path.open() as fh:
            for line in fh:
                if "!NATOM" in line:
                    return int(line.split()[0])
    except (OSError, ValueError):
        return 0
    return 0


@router.post("/md/jobs/{job_id}/estimate-production-disk")
async def estimate_md_production_disk(job_id: str, body: ProductionRequest) -> dict:
    """Forecast the disk a production stage of this job would write vs. free space.

    Atom count is exact (from the built PSF); the segment split mirrors
    :func:`_append_production_segments`.
    """
    from backend.core.disk_guard import forecast, namd_run_output_bytes

    job = _load_job(job_id)
    package_dir = job.package_dir(_workspace())
    n_atoms = _psf_atom_count(package_dir / f"{job.name_stem}.psf")
    total_steps = _production_fast_plan(job, body)["total_steps"]
    segments = [
        (max(100, int(round(total_steps * frac))), PRODUCTION_DCD_FREQ)
        for frac in (0.10, 0.40, 0.50)
    ]
    predicted = namd_run_output_bytes(segments, n_atoms)
    return forecast(package_dir if package_dir.exists() else _workspace(), predicted)


def _seed_design_name(body: CreateJobRequest) -> str:
    """Best-effort design name for a seeded job's list label (falls back to 'design').

    Reads the seed CG job's stored ``design_name`` so a draft/seeded job shows the
    real structure name in the list instead of the provisional 'design'.
    """
    ws = _workspace()
    try:
        if body.oxdna_job_id:
            from backend.core.oxdna_job import OxdnaJob  # noqa: PLC0415
            return OxdnaJob.load(body.oxdna_job_id, ws).design_name or "design"
        if body.mrdna_job_id:
            from backend.core.mrdna_job import MrdnaJob  # noqa: PLC0415
            return MrdnaJob.load(body.mrdna_job_id, ws).design_name or "design"
        if body.blade_job_id:
            from backend.core.blade_job import BladeJob  # noqa: PLC0415
            return BladeJob.load(body.blade_job_id, ws).design_name or "design"
    except Exception:  # noqa: BLE001 — a label lookup must never block job creation
        pass
    return "design"


def _apply_run_dir(job: MdJob, run_dir: Optional[str]) -> None:
    """Archive a FRESH job at ``run_dir`` from birth so its (multi-GB) NAMD outputs land
    there instead of the workspace/system disk.  Validates the target, sets the archive
    fields, creates ``<run_dir>/<job_id>``, and indexes it so the app resolves the job via
    the archive index (same mechanism as the post-hoc archive flow, just applied up front).
    No-op when ``run_dir`` is falsy.  Raises HTTPException(400) on a bad/unwritable target.
    """
    if not run_dir:
        return
    base = Path(run_dir).expanduser()
    if not base.is_dir():
        raise HTTPException(400, f"Run directory does not exist: {run_dir}")
    if not os.access(base, os.W_OK):
        raise HTTPException(400, f"Run directory is not writable: {run_dir}")
    dest = base.resolve() / job.job_id
    dest.mkdir(parents=True, exist_ok=True)
    job.archived = True
    job.archive_path = str(dest)
    ws = _workspace()
    idx = job_archive.read_index(ws, "md_jobs")
    idx[job.job_id] = str(dest)
    job_archive._write_index(ws, "md_jobs", idx)
    logger.info("run_dir: job %s archived-from-birth at %s", job.job_id, dest)


def _spawn_draft_job(body: CreateJobRequest, *, name: str) -> MdJob:
    """Create a seeded job in the DRAFT state (no solvation yet).

    Records the seed source + provenance + the default advanced params so the panel
    can pre-fill them; the expensive prep runs later in :func:`prepare_draft_job`.
    """
    job_threads = body.threads
    job = new_job(
        design_name    = name,
        protocol       = body.protocol,
        name_stem      = "",
        package_subdir = "",
        threads        = job_threads,
        devices        = body.devices,
        design_source_path = body.design_source_path,
        seed_oxdna_job_id  = body.oxdna_job_id,
        seed_mrdna_job_id  = body.mrdna_job_id,
        seed_blade_job_id  = body.blade_job_id,
    )
    job.execution_target = body.execution_target
    job.cluster_name = body.cluster_name or ("alpine" if body.execution_target == "alpine" else None)
    job.early_stop_relax = body.early_stop_relax
    job.early_stop_tier = (body.early_stop_tier or "B").upper()
    job.prep_params = body.model_dump()
    job.status = MdStatus.draft
    _apply_run_dir(job, body.run_dir)
    job.save(_workspace())
    logger.info("create_md_job: DRAFT job_id=%s design=%s seed_oxdna=%s seed_mrdna=%s",
                job.job_id, name, body.oxdna_job_id, body.mrdna_job_id)
    return job


VACUUM_PRESTAGE_RUN_KIND = "vacuum_prestage"


def _wants_vacuum_prestage(body: CreateJobRequest, design) -> bool:  # noqa: ARG001
    """RETIRED 2026-07-30 — always False.  NADOC does not need a pre-ladder shape step.

    The tutorial's §3.2 exists because caDNAno hands you an ABSTRACT lattice: helices
    exactly parallel, Holliday junctions abnormally stretched (their Figs. 3a/4a), a
    thing that is not a structure.  Something has to turn that into a physical
    conformation before it is worth solvating, and in vacuum is the cheap place.

    NADOC never has that problem.  Geometry here is DERIVED — helix axes and nucleotide
    positions come from the topology, the B-DNA constants and the design's deformations
    (the Three-Layer Law), so every design, including one imported from caDNAno, arrives
    already carrying NADOC's idealised positions.  exp50 measured this directly: the
    ideal build of ``6hbx100_90deg`` already holds ~98.5 degrees of per-helix centreline
    bend.  There is no parallel-helix lattice here for a vacuum step to unfold.

    And what the step actually did was not neutral.  Its interhelical repulsion surrogate
    is mrdna's push-bond rule, which needs a crossover-free span > 22 nt; honeycomb
    crossovers recur every 21 nt, so a dense NADOC bundle scores **zero** push bonds and
    the run proceeds with PME off, Coulomb truncated at 10 Å and no interhelical force
    term at all.  Measured consequence: bundles swelled 5.6-10 % (corroborated by exp48's
    independent P-P measurement, 20.6 -> 22.6 Å).  Unscreened swelling moves AWAY from the
    Mg-screened equilibrium the solvated ladder converges on, so the step was not merely
    unnecessary here — it was seeding the ladder from a worse structure.

    The one case this reasoning does NOT cover is a design carrying genuinely
    overstretched bonds — a scaffold connection spanning distant clusters, say — where
    the derived geometry IS unphysical.  That is a different problem (the strain is
    topological, not a missing relaxation) and is deliberately not addressed here.

    Kept as a function rather than deleted so the decision is documented at the point of
    use; ``backend/core/namd_vacuum.py`` stays dormant and revivable.
    """
    return False


def _spawn_vacuum_prestage(body: CreateJobRequest, *, design, name: str) -> MdJob:
    """Create + start the vacuum job, carrying the caller's request for the follow-up.

    The solvated run is NOT created here.  It is spawned by
    :func:`advance_vacuum_prestages` once these coordinates exist, so the whole thing
    goes through the ordinary job lifecycle (PID tracking, stop, resume, failure
    classification) instead of blocking a prep worker for the length of an MD run.
    """
    from backend.core.namd_vacuum import VACUUM_PROTOCOL  # noqa: PLC0415

    vac_body = body.model_copy(update={
        "protocol": VACUUM_PROTOCOL,
        "relax_preset": FAST_SHAPE,
        # The follow-up owns solvation; this stage has no box, salt or shell.
        "water_shell_nm": 0.0,
    })
    job = _spawn_prep_job(vac_body, design=design, seeded=False, name=name,
                          size_factor=1.0)
    job = MdJob.load(job.job_id, _workspace())
    job.run_kind = VACUUM_PRESTAGE_RUN_KIND
    # Everything the follow-up needs, recorded so a server restart cannot lose it.
    job.prep_params = dict(job.prep_params or {})
    job.prep_params["vacuum_followup"] = body.model_dump(mode="json")
    job.save(_workspace())
    logger.info("create_md_job: vacuum pre-stage job_id=%s design=%s", job.job_id, name)
    return job


def _spawn_prep_job(body: CreateJobRequest, *, design, seeded: bool, name: str,
                    size_factor: float, parent_job_id: Optional[str] = None,
                    existing_job: Optional[MdJob] = None) -> MdJob:
    """Create the MdJob, persist its prep params, and launch background prep.

    Shared by :func:`create_md_job` and :func:`refit_md_job` so a refit reuses the
    exact same solvation → ENM → config pipeline with one setting changed.  Pass
    ``existing_job`` to prepare a DRAFT in place (reusing its id + seed) instead of
    creating a fresh record — the "Relax from oxDNA" path.
    """
    ion_conc_mM = body.ion_conc_mM
    mg_conc_mM = body.mg_conc_mM
    if body.salt_mode == "screening":
        # The published origami recipe: the backbone is neutralised by Mg(H2O)6(2+) and
        # Cl- balances the excess — no Na+ at all (Methods Mol Biol 1811 §3.3).  The Mg
        # figure is a BULK FLOOR above neutralisation, not the whole magnesium content;
        # the counts come from namd_solvate.ion_counts against the audited charge.
        ion_conc_mM = 0.0
        mg_conc_mM = 12.5

    # Honour the requested thread count.  The old `min(threads, 4) if fast` cap
    # assumed fast always meant GPU-resident (GPU-bound, so +p4 == +p16).  It no
    # longer does: a water-shell-carved package runs the CUDA-offload path, whose
    # integrator + bonded forces are on the CPU and DO scale with threads (measured
    # on the 6hbx100_90deg carve: +p4 7.4 -> +p6 8.6 ns/day).  Even under true
    # GPU-resident the cap bought nothing (+p4 11.5, +p6 11.9, +p12 11.6 ns/day),
    # so there is no reason to override the user.
    job_threads = body.threads

    if existing_job is not None:
        # Prepare a draft in place: keep its id + seed, refresh the run knobs from
        # the (now user-adjusted) request.
        job = existing_job
        job.design_name = name or job.design_name
        job.protocol = body.protocol
        job.threads = job_threads
        job.devices = body.devices
        if body.design_source_path:
            job.design_source_path = body.design_source_path
    else:
        job = new_job(
            design_name    = name,
            protocol       = body.protocol,
            name_stem      = "",       # filled in after prep
            package_subdir = "",       # filled in after prep
            threads        = job_threads,
            devices        = body.devices,
            design_source_path = body.design_source_path,
            seed_oxdna_job_id  = body.oxdna_job_id if seeded else None,
            seed_mrdna_job_id  = body.mrdna_job_id if seeded else None,
            seed_blade_job_id  = body.blade_job_id if seeded else None,
            parent_job_id      = parent_job_id,
        )
        # Archive a fresh (non-draft) job at the requested run_dir BEFORE prep runs, so the
        # solvated package + trajectory are built there.  A draft was already placed by
        # _spawn_draft_job; a refit keeps its existing location.
        _apply_run_dir(job, body.run_dir)
    # Remote-execution tag (default "local"): submission itself happens later via
    # /md/jobs/{id}/submit-remote once the package is prepared and a cluster session
    # is connected.  Tagging here lets the UI show the intended target from creation.
    job.execution_target = body.execution_target
    job.cluster_name = body.cluster_name or ("alpine" if body.execution_target == "alpine" else None)
    job.early_stop_relax = body.early_stop_relax
    job.early_stop_tier = (body.early_stop_tier or "B").upper()
    # Capture the request so a later refit can rebuild the job with one knob moved.
    job.prep_params = body.model_dump()
    job.status = MdStatus.preparing
    job.save(_workspace())
    logger.info("create_md_job: job_id=%s design=%s protocol=%s seeded=%s",
                job.job_id, name, body.protocol, seeded)

    tracker = PrepTracker(
        build_prep_phases(
            seeded=seeded, size_factor=size_factor,
            implicit=(body.protocol == IMPLICIT_GBIS_PROTOCOL),
        ),
        clock=time.monotonic,
    )
    write_prep_progress(job.job_dir(_workspace()), tracker.snapshot())

    task = asyncio.create_task(_prepare_job_bg(
        job_id      = job.job_id,
        body        = body,
        design      = design,
        seeded      = seeded,
        ion_conc_mM = ion_conc_mM,
        mg_conc_mM  = mg_conc_mM,
        tracker     = tracker,
    ))
    _PREP_TASKS.add(task)
    task.add_done_callback(_PREP_TASKS.discard)

    return job


async def _prepare_job_bg(
    *,
    job_id: str,
    body: CreateJobRequest,
    design,
    seeded: bool,
    ion_conc_mM: float,
    mg_conc_mM: float,
    tracker: PrepTracker,
) -> None:
    """Background preparation: build seed (if any) → solvate → ENM → configs.

    Streams progress into ``{job_dir}/prep_progress.json`` via a 1 Hz heartbeat
    so the status websocket can render a live bar + ETA.  On any failure the job
    is marked ``failed`` with the error; on success ``queued`` (+ autostart).
    """
    ws = _workspace()
    job_dir = MdJob.load(job_id, ws).job_dir(ws)

    async def _heartbeat() -> None:
        try:
            while not tracker.is_done():
                write_prep_progress(job_dir, tracker.snapshot())
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    hb = asyncio.create_task(_heartbeat())

    try:
        seed_model = None
        seed_solute_coords = None
        if seeded:
            if body.oxdna_job_id:
                tracker.report("seed", None, "Reconstructing relaxed atomic model…")
                from backend.core.oxdna_runner import build_namd_seed  # noqa: PLC0415
                seed = await run_in_threadpool(build_namd_seed, body.oxdna_job_id, ws)
                local_design = seed.design
                seed_model = seed.atomistic_model
                _seed_src = f"oxDNA job {body.oxdna_job_id} (stage {seed.stage_name})"
            elif body.mrdna_job_id:
                tracker.report("seed", None, "Reconstructing relaxed atomic model…")
                from backend.core.mrdna_runner import build_namd_seed_from_mrdna  # noqa: PLC0415
                seed = await run_in_threadpool(build_namd_seed_from_mrdna, body.mrdna_job_id, ws)
                local_design = seed.design
                seed_model = seed.atomistic_model
                _seed_src = f"mrDNA job {body.mrdna_job_id} (stage {seed.stage_name})"
            else:
                # BLADE is already atomistic: no reconstruction, just read the exact relaxed
                # coordinates and feed them to solvation via solute_coords (below).
                tracker.report("seed", None, "Reading BLADE relaxed coordinates…")
                from backend.core.blade_runner import build_namd_seed_from_blade  # noqa: PLC0415
                seed = await run_in_threadpool(build_namd_seed_from_blade, body.blade_job_id, ws)
                local_design = seed.design
                seed_solute_coords = seed.solute_coords
                _seed_src = f"BLADE job {body.blade_job_id} ({seed.n_atoms} atoms)"
            seed_name = (local_design.metadata.name or "design").replace(" ", "_")
            job = MdJob.load(job_id, ws)
            job.design_name = seed_name
            job.save(ws)
            logger.info("prep %s: seeded from %s", job_id, _seed_src)
        else:
            local_design = design

        # Vacuum pre-stage seed.  Composes WITH the engine seeds above rather than
        # competing with them: those choose the DESIGN snapshot, this supplies the
        # starting COORDINATES for the same topology — which is exactly what the
        # tutorial's §3.3 does (it starts from hextube_min.pdb, the vacuum run's last
        # frame, not from the idealised build).
        if body.vacuum_job_id:
            tracker.report("seed", None, "Reading vacuum-relaxed coordinates…")
            from backend.core.namd_vacuum import build_namd_seed_from_vacuum  # noqa: PLC0415
            vac = await run_in_threadpool(
                build_namd_seed_from_vacuum, body.vacuum_job_id, ws)
            seed_solute_coords = vac.solute_coords
            logger.info("prep %s: seeded coordinates from vacuum job %s (%s, %d atoms)",
                        job_id, body.vacuum_job_id, vac.source, vac.n_atoms)

        if _sequenced_base_count(local_design) == 0:
            raise RuntimeError(_NO_SEQUENCE_MSG)

        # Pre-flight size check: if the user left the water shell on auto (0) and
        # the system won't fit the detected GPU, enable a carve that does — so a
        # large origami runs first time instead of OOM-ing.  Records the choice on
        # the job so the user can see what was auto-adjusted.
        # Auto water-shell carve caps the atom count to fit the compute target's
        # memory.  Implicit solvent (GBIS) has no water box → skip entirely.  For an
        # explicit CPU run there is no VRAM limit, so auto_water_shell sizes to host
        # RAM instead (see its `devices="cpu"` branch).
        water_shell_nm = body.water_shell_nm
        if not water_shell_nm and body.protocol != IMPLICIT_GBIS_PROTOCOL:
            from backend.core.md_vram import auto_water_shell  # noqa: PLC0415
            tracker.report("topology", None,
                           "Checking CPU memory headroom…" if body.devices.strip().lower() in ("cpu", "none")
                           else "Checking GPU memory headroom…")
            auto = await run_in_threadpool(
                auto_water_shell, local_design,
                padding_nm=body.padding_nm, devices=body.devices,
                atomistic_model=seed_model,
            )
            if auto["shell_nm"]:
                water_shell_nm = auto["shell_nm"]
                logger.info("prep %s: auto water shell %.2f nm — %s",
                            job_id, water_shell_nm, auto["note"])
                job = MdJob.load(job_id, ws)
                pp = dict(job.prep_params or {})
                pp["auto_water_shell_nm"] = water_shell_nm
                pp["auto_water_shell_note"] = auto["note"]
                job.prep_params = pp
                job.save(ws)

        # Persist the EXACT design this run is prepared from + its out-of-date
        # fingerprint, so a later design edit flags the job and "Roll & run" can
        # restore this exact state (mirrors oxDNA).
        from backend.core.oxdna_staleness import (
            design_build_fingerprint, effective_feature_log_position)
        (job_dir / "design.json").write_text(local_design.model_dump_json())
        job = MdJob.load(job_id, ws)
        job.design_fingerprint = design_build_fingerprint(local_design)
        job.feature_log_position = effective_feature_log_position(local_design)
        job.save(ws)

        if body.protocol == IMPLICIT_GBIS_PROTOCOL:
            from backend.core.namd_gbis import prepare_implicit_gbis_namd  # noqa: PLC0415
            prepare = prepare_implicit_gbis_namd
        elif body.protocol == EQUILIBRIUM_AWARE_PROTOCOL:
            prepare = prepare_equilibrium_aware_namd
        else:
            prepare = prepare_mgh_slow_release
        # A BLADE or vacuum-prestage seed feeds an EXACT all-atom conformation straight
        # into solvation via solute_coords — which only aligns under the full psfgen
        # topology (with hydrogens), so force it.  The equilibrium-aware protocol ALREADY
        # pins require_full_topology=True internally, so passing it again there would be a
        # duplicate-kwarg collision; only add it for the legacy path (which defaults
        # False).  GBIS is rejected up front for both seeds, so it never reaches here with
        # solute_coords.
        seed_kwargs: dict = {}
        if seed_solute_coords is not None:
            seed_kwargs["solute_coords"] = seed_solute_coords
            if body.protocol != EQUILIBRIUM_AWARE_PROTOCOL:
                seed_kwargs["require_full_topology"] = True
        # The catenated-seed override is an md_protocols concept; the GBIS prep has its
        # own signature and never sees it.
        if body.protocol != IMPLICIT_GBIS_PROTOCOL:
            seed_kwargs["allow_catenated_seed"] = body.allow_catenated_seed
        package_subdir, name_stem, segments = await run_in_threadpool(
            prepare,
            local_design,
            job_dir,
            ion_conc_mM     = ion_conc_mM,
            mg_conc_mM      = mg_conc_mM,
            salt_mode       = body.salt_mode,
            padding_nm      = body.padding_nm,
            water_shell_nm  = water_shell_nm,
            minimize_steps  = body.minimize_steps,
            atomistic_model = seed_model,
            declash         = body.declash,
            force_soft      = body.force_soft,
            fast            = body.fast,
            gpu_resident_mode = body.gpu_resident or "auto",
            production_timestep_fs = body.production_timestep_fs,
            devices         = body.devices,
            anchors         = body.anchors,
            field           = body.field,
            progress        = tracker.report,
            **seed_kwargs,
        )
        logger.info("prep %s: done; package=%s name_stem=%s segments=%d",
                    job_id, package_subdir, name_stem, len(segments))
    except Exception as exc:
        logger.error("prep %s: FAILED: %s", job_id, exc, exc_info=True)
        tracker.fail(str(exc))
        hb.cancel()
        job = MdJob.load(job_id, ws)
        job.status = MdStatus.failed
        job.error = f"Preparation failed: {exc}"
        job.save(ws)
        clear_prep_progress(job_dir)
        return

    tracker.finish()
    hb.cancel()

    job = MdJob.load(job_id, ws)
    job.package_subdir = package_subdir
    job.name_stem      = name_stem
    job.segments       = [
        MdSegmentStatus(
            name    = s.name,
            stage   = s.stage,
            percent = s.percent,
            steps   = s.steps,
            status  = "pending",
        )
        for s in segments
    ]
    # The pre-ladder minimisation is not a segment (see MdJob.minimization), but on a
    # large box it runs for tens of minutes — record it so the timeline shows it running
    # rather than looking idle, and confirms it finished.
    job.minimization = _minimization_from_package(job.package_dir(ws))
    job.status = MdStatus.queued
    job.save(ws)
    clear_prep_progress(job_dir)

    if body.autostart and job.execution_target == "local":
        logger.info("prep %s: autostart=True, launching", job_id)
        start_job(job, ws)
    elif body.autostart:
        logger.info("prep %s: remote target %s — submit via /submit-remote when connected",
                    job_id, job.execution_target)


def _minimization_from_package(package_dir: Path) -> Optional[MdSegmentStatus]:
    """The package manifest's pre-ladder step, for the job timeline. None if unreadable.

    Never raises: this runs at the tail of a successful prep, and a job that solvated
    fine must not be failed over a missing timeline row.
    """
    from backend.core.md_protocols import minimization_status  # noqa: PLC0415

    try:
        manifest = json.loads((package_dir / "manifest.json").read_text())
    except Exception:  # noqa: BLE001 — absent/unreadable manifest → no row, not a failure
        return None
    return minimization_status(manifest)


def _backfill_failure_kind(job: MdJob) -> None:
    """Lazily classify a failed job's failure_kind (one-time, then persisted).

    Jobs that failed before failure_kind existed get classified here so the "Fix"
    button can appear.  Scans only the few most-recent package logs and persists
    the result, so each job is examined at most once.
    """
    if job.status != MdStatus.failed or job.failure_kind is not None:
        return
    pkg = job.package_dir(_workspace())
    kind = "other"
    if pkg.exists():
        from backend.core.md_vram import classify_failure_log_file  # noqa: PLC0415
        logs = sorted(pkg.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        for lg in logs[:4]:
            k = classify_failure_log_file(lg)
            if k != "other":
                kind = k
                break
    job.failure_kind = kind
    job.save(_workspace())


def _namd_running_fraction(job: MdJob, ws) -> float | None:
    """Live overall progress fraction (0..1) for a RUNNING NAMD job, for the master
    progress bar.  ``None`` for non-running jobs (the bar falls back to done/total
    segments).  Reads only the currently-running segment's log (cheap: ≤1 per running
    job), mirroring the WS ``segment_progress`` so a single-segment production advances
    instead of sitting at 0 %."""
    if job.status != MdStatus.running:
        return None
    segs = job.segments or []
    total = len(segs)
    if not total:
        return None
    from backend.core.namd_metrics import last_namd_timestep_fast, overall_fraction  # noqa: PLC0415
    done = sum(1 for s in segs if s.status == "done")
    ts = None
    steps = None
    idx = job.current_segment_idx
    if 0 <= idx < total and segs[idx].status == "running":
        seg = segs[idx]
        steps = seg.steps
        log_path = job.package_dir(ws) / f"{seg.name}.log"
        if log_path.exists():
            # Tail-read only — this is a ~1.5 s poll; reading the whole growing log each
            # time contended with NAMD's own writes and tripped the slow-request popup.
            try:
                ts = last_namd_timestep_fast(log_path)
            except Exception:
                ts = None
    return overall_fraction(done, total, ts, steps)


# Strong refs to in-flight background dir-size walks so the event loop can't GC them
# mid-walk (asyncio.create_task only holds a weak ref).
_SIZE_WARM_TASKS: set = set()


@router.get("/md/jobs")
async def list_md_jobs() -> list[dict]:
    from backend.core.oxdna_staleness import current_active_design_fingerprint
    from backend.core.design_disk_usage import dir_size_bytes_cached_only, warm_dir_sizes
    ws = _workspace()
    jobs = MdJob.list_jobs(ws)
    jobs = [reconcile_job_status(j, ws) for j in jobs]
    current_fp = current_active_design_fingerprint()
    out: list[dict] = []
    to_warm: list = []
    for j in jobs:
        _backfill_failure_kind(j)
        d = j.to_dict()
        d["out_of_date"] = _md_job_out_of_date(j, current_fp)
        # Cache-only: never block the poll on a multi-GB archived-run stat-walk.  An
        # uncached size comes back None (frontend renders it blank) and is filled in by
        # the background warm below, appearing on the next poll.
        job_dir = j.job_dir(ws)
        size = dir_size_bytes_cached_only(job_dir)
        d["size_bytes"] = size
        if size is None:
            to_warm.append(job_dir)
        d["early_stop_pending"] = pending_early_stop(j.job_id)
        frac = _namd_running_fraction(j, ws)
        if frac is not None:
            d["progress_fraction"] = frac
        out.append(d)
    if to_warm:
        # Fire-and-forget: walk the uncached dirs in a threadpool AFTER returning, keeping
        # a task ref so the loop doesn't GC it mid-walk.  warm_dir_sizes dedups, so
        # overlapping polls never stampede the same directory.
        task = asyncio.create_task(run_in_threadpool(warm_dir_sizes, to_warm))
        _SIZE_WARM_TASKS.add(task)
        task.add_done_callback(_SIZE_WARM_TASKS.discard)
    return out


@router.get("/md/jobs/{job_id}")
async def get_md_job(job_id: str) -> dict:
    from backend.core.oxdna_staleness import current_active_design_fingerprint
    job = _load_job(job_id)
    d = job.to_dict()
    # Every job that predates MdJob.minimization has None here.  Read it back off the
    # package manifest — ONE file per opened job, so the timeline shows the minimisation
    # for existing runs too.  Deliberately not persisted: a GET should not write job.json.
    if d.get("minimization") is None:
        row = _minimization_from_package(job.package_dir(_workspace()))
        if row is not None:
            d["minimization"] = asdict(row)
    d["out_of_date"] = _md_job_out_of_date(job, current_active_design_fingerprint())
    d["early_stop_pending"] = pending_early_stop(job_id)
    return d


@router.get("/md/jobs/{job_id}/display")
async def get_md_job_display(job_id: str) -> dict:
    """Return the manifest and latest segment suitable for DNA-only display."""
    job = _load_job(job_id)
    package_dir = job.package_dir(_workspace())
    manifest = package_dir / "nadoc_md_run.json"
    if not manifest.exists():
        manifest = package_dir / "manifest.json"

    segment_name, dcd_path = _latest_display_segment(job)
    ready_idx, ready_spec, ready_reason, ready_warning = _production_ready_checkpoint(job)
    continue_idx, continue_spec, continue_reason = _completed_production_checkpoint(job)
    ready = manifest.exists() and dcd_path is not None
    busy = job.status in {MdStatus.running, MdStatus.preparing}

    # Seeded jobs no longer skip relaxation — they run the restrained ladder from
    # the seed, then produce from its checkpoint like any job (from_seed removed).
    from_seed = False
    production_ready = ready_spec is not None and not busy
    if ready_spec is not None:
        production_checkpoint = ready_spec.name
        production_warning = ready_warning
    else:
        production_checkpoint = None
        production_warning = ""

    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "ready": ready,
        "config_path": str(manifest.resolve()) if manifest.exists() else None,
        "package_dir": str(package_dir.resolve()) if package_dir.exists() else None,
        "segment_name": segment_name,
        "trajectory_path": str(dcd_path.resolve()) if dcd_path else None,
        "production_ready": production_ready,
        "production_from_seed": from_seed,
        "production_checkpoint": production_checkpoint,
        "production_ready_reason": "" if production_ready else ready_reason,
        "production_warning": production_warning if production_ready else "",
        "production_continue_available": continue_spec is not None,
        "production_continue_checkpoint": continue_spec.name if continue_spec else None,
        "production_continue_reason": "" if continue_spec else continue_reason,
    }


@router.delete("/md/jobs/{job_id}")
async def delete_md_job(job_id: str) -> dict:
    """Delete an MD job and every generated file/folder beneath its job dir."""
    from backend.core.job_archive import purge_index_entry
    ws = _workspace()
    job = _load_job(job_id)
    if is_running(job_id) or job.status == MdStatus.running:
        raise HTTPException(400, "Stop the MD job before deleting it")
    job_dir = job.job_dir(ws)
    if job_dir.exists():
        shutil.rmtree(job_dir)
    purge_index_entry(ws, "md_jobs", job_id)   # drop archived-job index entry if any
    return {"ok": True, "job_id": job_id, "deleted": str(job_dir)}


# ── Archive / unarchive ────────────────────────────────────────────────────────

class ArchiveRequest(BaseModel):
    dest_root: str   # parent directory; the job moves to <dest_root>/<job_id>


@router.post("/md/jobs/{job_id}/archive", status_code=202)
async def archive_md_job(job_id: str, body: ArchiveRequest) -> dict:
    """Start moving a job's folder to ``dest_root`` in the background (poll status)."""
    from backend.core import job_archive
    ws = _workspace()
    job = _load_job(job_id)
    if is_running(job_id) or job.status == MdStatus.running:
        raise HTTPException(400, "Stop the MD job before archiving it")
    try:
        job_archive.start_archive(job, ws, "md_jobs", Path(body.dest_root))
    except (ValueError, FileExistsError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "job_id": job_id, "action": "archive"}


@router.post("/md/jobs/{job_id}/unarchive", status_code=202)
async def unarchive_md_job(job_id: str) -> dict:
    """Start moving an archived job's folder back into the workspace (poll status)."""
    from backend.core import job_archive
    ws = _workspace()
    job = _load_job(job_id)
    try:
        job_archive.start_unarchive(job, ws, "md_jobs")
    except (ValueError, FileExistsError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "job_id": job_id, "action": "unarchive"}


@router.get("/md/jobs/{job_id}/archive-status")
async def md_archive_status(job_id: str) -> dict:
    from backend.core import job_archive
    return job_archive.task_status("md_jobs", job_id) or {"state": "idle"}


def _assert_cell_fits_a_free_run(job: MdJob, length_ns: float, *, allow: bool) -> None:
    """Refuse a long UNRESTRAINED run in a cell the solute can rotate out of.

    A relaxation package is deliberately bbox-sized (see
    ``namd_solvate.ROTATION_FREE_NS_THRESHOLD``): its ladder is restrained throughout
    bar one 4.8 ns stage, and a rotation-sized cell would cost several times the water
    for a reorientation that never happens.  Production is the opposite case — tens to
    hundreds of nanoseconds with nothing holding the solute — and that is exactly the
    run that walks a rod-shaped origami into its own periodic image.

    The package already records the verdict: ``box_check.fits_rotated`` is measured on
    every build.  This just refuses to ignore it.
    """
    from backend.core.namd_solvate import ROTATION_FREE_NS_THRESHOLD  # noqa: PLC0415

    if allow or length_ns <= ROTATION_FREE_NS_THRESHOLD:
        return
    try:
        manifest = json.loads(
            (job.package_dir(_workspace()) / "manifest.json").read_text())
        check = (manifest.get("solvation") or {}).get("box_check") or {}
    except Exception:  # noqa: BLE001 — never block on an unreadable diagnostic
        return
    if not check.get("measured", True) or check.get("fits_rotated", True):
        return
    gap = check.get("image_gap_rotated_ang")
    how_close = (f" a turned solute comes within {gap:.0f} Å of its own periodic image;"
                 if isinstance(gap, (int, float)) else "")
    raise HTTPException(400, (
        f"This package's cell is too small for a {length_ns:g} ns unrestrained run. It "
        f"was sized for the relaxation ladder, which holds the solute still; free of "
        f"restraints the structure rotates, and in this cell{how_close} the trajectory "
        f"would be corrupted without ever failing. Prepare a fresh package for "
        f"production (it will be rotation-sized), keep the run under "
        f"{ROTATION_FREE_NS_THRESHOLD:g} ns, or resend with allow_undersized_cell=true "
        f"if you know the solute is effectively spherical."))


@router.post("/md/jobs/{job_id}/production")
async def append_md_production(job_id: str, body: ProductionRequest) -> dict:
    """Append a final production stage after the restraint-release ladder passes."""
    job = _load_job(job_id)
    if is_running(job_id) or job.status in (MdStatus.running, MdStatus.preparing):
        raise HTTPException(400, "Cannot append production while the job is running")
    _assert_md_job_current(job)
    plan = _production_fast_plan(job, body)
    total_steps, length_ns = plan["total_steps"], plan["length_ns"]
    _assert_cell_fits_a_free_run(job, length_ns, allow=body.allow_undersized_cell)
    segments = _append_production_segments(
        job,
        plan,
        continue_from_production=body.continue_from_production,
    )
    job = _load_job(job_id)
    if body.autostart:
        job.status = MdStatus.running
        job.save(_workspace())
        start_job(job, _workspace())
    return {
        "ok": True,
        "job": job.to_dict(),
        "segments_added": [s.name for s in segments],
        "steps": total_steps,
        "length_ns": length_ns,
        "autostart": body.autostart,
    }


class ProductionRunRequest(BaseModel):
    """Spawn ONE production run as a child job seeded from a completed parent.

    Mirrors the oxDNA ``/oxdna/jobs/{id}/run`` child-job model: the relaxation stays a
    distinct, selectable entry and each production nests under it, so the user can fan
    out several independent productions (distinct velocity seeds) from one equilibrated
    structure — or chain one (spawn a production off a completed production child)."""
    steps: Optional[int] = Field(None, ge=100, le=50_000_000,
                                 description="Raw integration steps (falls back to length_ns)")
    length_ns: Optional[float] = Field(None, gt=0.0, le=100.0,
                                       description="Simulated ns (used if steps omitted)")
    autostart: bool = Field(True, description="Start the child right away (local target only)")
    production_timestep_fs: Optional[float] = Field(
        None,
        description="Integrator timestep (fs) for this child: 1.0, 2.0 or 4.0. Sending it "
                    "PINS the choice — an unrunnable one fails the child with "
                    "FAILURE_TIMESTEP_PINNED instead of silently substituting another. Omit "
                    "to inherit the package manifest's prep-time value.",
    )

    @field_validator("production_timestep_fs")
    @classmethod
    def _sanctioned_child_timestep(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v not in (1.0, 2.0, 4.0):
            raise ValueError("production_timestep_fs must be 1.0, 2.0, or 4.0")
        return None if v is None else float(v)

    gpu_resident: Optional[str] = Field(
        None,
        description="GPU-resident mode for this child: 'auto' (size gate), 'on' or 'off'. "
                    "Omit to inherit the package's prep-time choice.",
    )

    @field_validator("gpu_resident")
    @classmethod
    def _sanctioned_child_gpu_resident(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s not in ("auto", "on", "off"):
            raise ValueError("gpu_resident must be 'auto', 'on', or 'off'")
        return s
    execution_target: Optional[str] = Field(
        None, description="'local' or 'alpine'; defaults to the parent's target. An "
                          "'alpine' child is left queued for the submit-review card.")
    cluster_name: Optional[str] = Field(None, description="Cluster for an alpine target")
    dcd_freq: Optional[int] = Field(
        None, ge=100, le=1_000_000,
        description="DCD trajectory output interval (steps). Defaults to PRODUCTION_DCD_FREQ "
                    "(2500 = every 10 ps at 4 fs). Lower it for denser sampling when the "
                    "trajectory feeds fluctuation-based parameter extraction (FEM/SNUPI/mrdna).")


def _production_seed_checkpoint(parent: MdJob) -> tuple[Optional[SegmentSpec], str, str]:
    """Resolve the coords a production child should seed from: ``(spec, warning, reason)``.

    A production child (chaining) seeds from the parent's completed production stage;
    a relaxation parent seeds from its equilibrated (restraint-released) checkpoint."""
    if parent.run_kind == "production":
        _idx, spec, reason = _completed_production_checkpoint(parent)
        return spec, "", reason
    _idx, spec, reason, warning = _production_ready_checkpoint(parent)
    return spec, warning, reason


@router.post("/md/jobs/{parent_id}/production-run")
async def spawn_md_production(parent_id: str, body: ProductionRunRequest) -> dict:
    """Branch a production run off a completed relaxation (or production) as a CHILD job.

    The parent relaxation is left untouched and stays selectable; the child is a
    production-only package seeded from the parent's equilibrated coordinates with a
    distinct NAMD velocity seed (``reinitvels``), so repeated calls fan out independent
    productions that render nested under the parent (mirroring oxDNA's child runs)."""
    from backend.core import md_ensemble

    parent = _load_job(parent_id)
    if is_running(parent_id) or parent.status != MdStatus.completed:
        raise HTTPException(
            400, "Production requires a completed relaxation (or production) to seed from.")
    _assert_md_job_current(parent)

    spec, warning, reason = _production_seed_checkpoint(parent)
    if spec is None:
        raise HTTPException(
            400, reason or "No equilibrated checkpoint is available to seed production from.")
    output = parent.package_dir(_workspace()) / "output"
    if not all((output / f"{spec.name}.{ext}").exists() for ext in ("coor", "xsc")):
        raise HTTPException(400, f"Checkpoint {spec.name} coordinates were not found locally.")

    plan = _production_fast_plan(parent, ProductionRequest(
        steps=body.steps, length_ns=body.length_ns, autostart=False,
        production_timestep_fs=body.production_timestep_fs,
        gpu_resident=body.gpu_resident,
    ))
    # ⚠️ `parent` is the COMPLETED RELAXATION and is READ-ONLY from here.  An earlier
    # version failed the parent when it disliked a production setting, which flipped a
    # finished 12/12 ladder to "failed" and discarded the record of hours of successful
    # work.  Nothing about a production request is a property of the run that produced
    # the coordinates.

    # Distinct velocity seed per production child of this parent, so a fan-out samples
    # independent trajectories from the same equilibrated coords.  Replica 0 uses the
    # same 54321 as the historical single-run production path.
    siblings = [
        j for j in MdJob.list_jobs(_workspace())
        if j.parent_job_id == parent.job_id and j.run_kind == "production"
    ]
    index = len(siblings)
    seed = md_ensemble.generate_seeds(md_ensemble._DEFAULT_BASE_SEED, index + 1)[-1]

    child = new_job(
        design_name=parent.design_name,
        protocol=parent.protocol,
        name_stem=parent.name_stem,
        package_subdir=parent.package_subdir,
        threads=parent.threads,
        devices=parent.devices,
        design_source_path=parent.design_source_path,
        parent_job_id=parent.job_id,
        ensemble_seed=seed,
        ensemble_index=index,
        run_kind="production",
    )
    # Run target comes from the request (the panel's Local/Alpine radio), NOT the
    # parent — a locally-relaxed structure can be produced on Alpine and vice-versa.
    target = (body.execution_target or parent.execution_target or "local").lower()
    child.execution_target = target
    child.cluster_name = (
        body.cluster_name or (parent.cluster_name if target == "alpine" else None)
        or ("alpine" if target == "alpine" else None))
    # Carry the parent's staleness provenance so a production child never spuriously
    # flags out-of-date — it derives from the parent's frozen package, not the live design.
    child.design_fingerprint = parent.design_fingerprint
    child.feature_log_position = parent.feature_log_position

    # INHERIT THE PARENT'S ARCHIVE. A relaxation is archived precisely because its job
    # folder is too big for the system disk — and production is the part that writes the
    # LARGE trajectory. A child that silently defaulted to archived=False would resolve
    # job_dir() back to workspace/md_jobs/<id> and dump gigabytes of DCD onto the very
    # disk the parent was moved off, which is the opposite of what the user asked for.
    # Sibling of the parent's folder, so one archive root holds the whole family.
    if parent.archived and parent.archive_path:
        child.archived = True
        child.archive_path = str(Path(parent.archive_path).parent / child.job_id)
        Path(child.archive_path).mkdir(parents=True, exist_ok=True)
        idx = job_archive.read_index(_workspace(), "md_jobs")
        idx[child.job_id] = child.archive_path
        job_archive._write_index(_workspace(), "md_jobs", idx)

    md_ensemble.build_replica_package(
        parent, child,
        seed=seed, index=index,
        total_steps=plan["total_steps"], length_ns=plan["length_ns"],
        timestep_fs=plan["timestep_fs"], fast=plan["fast"],
        ready_checkpoint=spec.name, workspace=_workspace(),
        dcd_freq=(body.dcd_freq or PRODUCTION_DCD_FREQ),
        force_resident=plan.get("force_resident"),
    )

    # Local target autostarts the NAMD run immediately; an Alpine child is left
    # 'queued' so the submit-review card can size resources + hand it to SLURM
    # (mirrors the relaxation + ensemble Alpine flow).
    if body.autostart and target == "local":
        child.status = MdStatus.running
        child.save(_workspace())
        start_job(child, _workspace())

    return {
        "ok": True,
        "job": child.to_dict(),
        "parent_job_id": parent.job_id,
        "seed": seed,
        "index": index,
        "length_ns": plan["length_ns"],
        "steps": plan["total_steps"],
        "warning": warning,
        "autostart": bool(body.autostart),
    }


@router.post("/md/jobs/{job_id}/revert-production")
async def revert_md_production(job_id: str) -> dict:
    """Migrate a legacy job whose production was APPENDED onto the relaxation (the old
    same-job layout) back to a clean completed relaxation, so relax + production become
    separate entries.  Non-destructive — the production confs/output are moved to
    ``_superseded_production/`` in the job dir, not deleted.  After this the Production
    button spawns a proper child run (``spawn_md_production``)."""
    from backend.core.md_job import revert_appended_production

    job = _load_job(job_id)
    if is_running(job_id) or job.status in (MdStatus.running, MdStatus.preparing):
        raise HTTPException(400, "Stop the job before separating its production run.")
    report = revert_appended_production(job, _workspace())
    if not report.get("reverted"):
        raise HTTPException(400, report.get("reason", "Nothing to revert on this job."))
    return {"ok": True, "job": _load_job(job_id).to_dict(), **report}


class EnsembleProductionRequest(BaseModel):
    """Stage N independent NAMD production replicas (distinct seeds) from a parent."""
    n_replicas: int = Field(4, ge=1, le=64, description="Number of independent replicas")
    steps: Optional[int] = Field(None, ge=100, le=50_000_000,
                                 description="Raw integration steps per replica")
    length_ns: Optional[float] = Field(None, gt=0.0, le=100.0,
                                       description="Simulated ns per replica (used if steps omitted)")
    base_seed: int = Field(54321, description="First NAMD seed; replica i uses base_seed + i")
    cluster_name: str = Field("alpine")
    partition: str = Field("amilan", description="Default SLURM partition (CPU by default)")
    safety_factor: float = Field(1.5, gt=0.0)


@router.post("/md/jobs/{parent_id}/ensemble-production")
async def stage_md_ensemble(parent_id: str, body: EnsembleProductionRequest) -> dict:
    """Create N production-only replica child jobs from a completed relaxation parent.

    Offline file ops — no cluster connection needed.  Each replica shares the parent's
    equilibrated coordinates but reinitialises velocities from its own seed, and is left
    PREPARED (``queued``, no SLURM id) for a subsequent one-shot ``ensemble-submit``.
    """
    from backend.core import md_ensemble

    parent = _load_job(parent_id)
    if parent.status != MdStatus.completed:
        raise HTTPException(400, "The parent relaxation must be completed before staging an ensemble.")

    _idx, spec, reason, _warning = _production_ready_checkpoint(parent)
    if spec is None:
        raise HTTPException(400, reason or "No equilibrated checkpoint is available on the parent.")
    output = parent.package_dir(_workspace()) / "output"
    if not all((output / f"{spec.name}.{ext}").exists() for ext in ("coor", "xsc")):
        raise HTTPException(400, f"Equilibrated checkpoint {spec.name} coordinates were not found locally.")

    plan = _production_fast_plan(parent, ProductionRequest(
        steps=body.steps, length_ns=body.length_ns, autostart=False,
    ))
    seeds = md_ensemble.generate_seeds(body.base_seed, body.n_replicas)

    children = []
    for i, seed in enumerate(seeds):
        child = new_job(
            design_name=parent.design_name,
            protocol=parent.protocol,
            name_stem=parent.name_stem,
            package_subdir=parent.package_subdir,
            threads=parent.threads,
            devices=parent.devices,
            design_source_path=parent.design_source_path,
            parent_job_id=parent.job_id,
            ensemble_seed=seed,
            ensemble_index=i,
        )
        child.execution_target = "alpine"
        child.cluster_name = body.cluster_name
        # Carry the parent's staleness provenance so replica rows never spuriously flag
        # out-of-date — they derive from the parent's frozen package, not the live design.
        child.design_fingerprint = parent.design_fingerprint
        child.feature_log_position = parent.feature_log_position
        md_ensemble.build_replica_package(
            parent, child,
            seed=seed, index=i,
            total_steps=plan["total_steps"], length_ns=plan["length_ns"],
            timestep_fs=plan["timestep_fs"], fast=plan["fast"],
            ready_checkpoint=spec.name, workspace=_workspace(),
        )
        children.append(child.to_dict())

    return {
        "ok": True,
        "parent_job_id": parent_id,
        "n_replicas": body.n_replicas,
        "seeds": seeds,
        "partition": body.partition,
        "length_ns": plan["length_ns"],
        "children": children,
    }


class EnsembleSubmitRequest(BaseModel):
    """Submit every prepared replica of a parent to the cluster in one action."""
    cluster_name: str = Field("alpine")
    resources: Optional[dict] = Field(
        None, description="Shared SLURM resources applied to every replica (override; "
                          "omit to auto-size on the partition below).",
    )
    partition: str = Field("amilan")
    safety_factor: float = Field(1.5, gt=0.0)


@router.post("/md/jobs/{parent_id}/ensemble-submit")
async def submit_md_ensemble(parent_id: str, body: EnsembleSubmitRequest) -> dict:
    """Submit every prepared, not-yet-submitted replica of a parent (needs a live session).

    Replicas are identical size, so resources are sized ONCE (default amilan CPU) and
    applied to all.  One child's failure doesn't abort the rest — the response lists
    per-replica slurm ids + errors, and each is submitted as its own sbatch (own SLURM
    id) so the supervisor tracks them independently.
    """
    from backend.core import cluster_config, cluster_ssh, md_executor

    _load_job(parent_id)  # 404 if the parent is gone
    mgr = cluster_ssh.get_manager()
    if not mgr.is_connected():
        raise HTTPException(409, "Not connected to a cluster — connect first (Duo).")

    profiles = cluster_config.load_profiles(_workspace())
    profile = profiles.get(body.cluster_name)
    if profile is None:
        raise HTTPException(404, f"Unknown cluster profile {body.cluster_name!r}.")

    replicas = [
        j for j in MdJob.list_jobs(_workspace())
        if j.parent_job_id == parent_id and j.ensemble_seed is not None
        and j.execution_target == "alpine" and not j.slurm_job_id
    ]
    replicas.sort(key=lambda j: (j.ensemble_index if j.ensemble_index is not None else 0))
    if not replicas:
        raise HTTPException(400, "No prepared, unsubmitted replicas for this parent.")

    if body.resources:
        resources = body.resources
    else:
        sizing = _size_prepared_job(replicas[0], profile, body.safety_factor, partition=body.partition)
        if sizing is None:
            raise HTTPException(400, "Replica package is not prepared yet — cannot size resources.")
        resources = sizing["resources"]

    submitted, errors = [], []
    for child in replicas:
        try:
            job = await md_executor.submit_job(
                child, _workspace(), profile=profile, resources=resources, conn=mgr,
            )
            submitted.append({"job_id": job.job_id, "slurm_job_id": job.slurm_job_id})
        except cluster_ssh.ClusterSSHError as exc:
            _record_submit_failure(child, f"Cluster transport error: {exc}")
            errors.append({"job_id": child.job_id, "error": f"Cluster transport error: {exc}"})
        except (ValueError, RuntimeError) as exc:
            _record_submit_failure(child, str(exc))
            errors.append({"job_id": child.job_id, "error": str(exc)})

    return {
        "ok": not errors,
        "parent_job_id": parent_id,
        "submitted": submitted,
        "errors": errors,
        "resources": resources,
    }


@router.post("/md/jobs/{job_id}/roll-design")
async def roll_md_job_design(job_id: str) -> dict:
    """Restore the design to the EXACT state this MD job was prepared from (its frozen
    snapshot), saving the current edits as a "Return to latest" loadout branch — so a
    stale job's ⚠ clears and the trajectory display matches the structure again."""
    from backend.api.crud import roll_active_to_job_state

    job = _load_job(job_id)
    design = _md_snapshot_design(job)
    if design is None:
        raise HTTPException(400, "This MD job has no saved design snapshot to roll back to.")
    name = job.design_name or "this job"
    return roll_active_to_job_state(design, job.feature_log_position, f"Latest — before viewing {name}")


@router.post("/md/jobs/{job_id}/start")
async def start_md_job(job_id: str) -> dict:
    """Start or resume a queued/stopped/failed job."""
    job = _load_job(job_id)

    if is_running(job_id):
        return {"ok": True, "message": "Job already running"}

    if job.status in (MdStatus.running, MdStatus.completed):
        raise HTTPException(400, f"Job is {job.status.value} — cannot start")

    # ── RunPod: rent a GPU, run the ladder there, destroy the pod ─────────────
    # Must come BEFORE find_namd(): a RunPod job runs NAMD on the POD (the patched
    # sm_89 build on the network volume), so requiring a LOCAL NAMD would refuse to
    # start a perfectly valid remote job on a machine that has no GPU at all.
    if job.execution_target == "runpod":
        return await _start_runpod_job(job)

    # Re-check NAMD available (local execution only)
    try:
        find_namd()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))

    job.status = MdStatus.running
    job.error = None
    job.failure_kind = None
    job.user_stopped = False  # explicit (re)start clears the no-auto-resume flag
    job.save(_workspace())

    start_job(job, _workspace())
    return {"ok": True, "job_id": job_id, "status": "running"}


@router.post("/md/jobs/{job_id}/gpu-decision")
async def resolve_md_gpu_decision(job_id: str, body: dict) -> dict:
    """Resolve a Gate-B GPU-resident fallback decision on a paused job.

    ``choice`` "offload" downgrades to the slower GPU mode and resumes; "cancel"
    stops the job. The resume skips the resident probe (no conf still requests it).
    """
    choice = str((body or {}).get("choice", "")).strip()
    if choice not in ("offload", "cancel"):
        raise HTTPException(400, "choice must be 'offload' or 'cancel'")
    job = _load_job(job_id)
    if not job.decision:
        raise HTTPException(400, "Job has no pending GPU decision")
    try:
        resolve_gpu_decision(job, choice, _workspace())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if choice == "offload":
        start_job(job, _workspace())
        return {"ok": True, "job_id": job_id, "status": "running"}
    return {"ok": True, "job_id": job_id, "status": job.status.value}


async def _start_runpod_job(job: MdJob) -> dict:
    """Launch a job on a rented RunPod GPU.

    Resume is FREE here and needs no special path: the chain script skips any step whose
    ``output/<name>.coor`` already sits on the network volume, so re-starting an
    interrupted job simply continues it. (Alpine needs a bespoke resume because SLURM
    walltimes cut MID-segment; a reclaimed pod does not.)
    """
    from backend.api import routes_runpod
    from backend.core import runpod_preflight, runpod_supervisor

    session = routes_runpod._SESSION  # noqa: SLF001 — the in-memory RunPod session

    if runpod_supervisor.is_running(job.job_id):
        return {"ok": True, "message": "Job already running on a pod"}

    # ── PRE-FLIGHT: never rent a pod we already know cannot run the job ───────
    # Each check corresponds to a failure that has already cost a real, billing pod:
    # a wrong-arch GPU that boots and dies at step 0; a missing SSH key on a pod that
    # refuses every connection; no volume, so no NAMD and no packages.
    try:
        n_atoms = runpod_supervisor.n_atoms_for(job, _workspace())
    except RuntimeError:
        n_atoms = None

    stock = None
    if session.is_connected() and session.api_key:
        try:
            stock = await runpod_preflight.fetch_gpu_stock(session.api_key)
        except Exception:  # noqa: BLE001 — becomes a FAILED check, not a 500
            logger.warning("runpod: GPU stock lookup failed", exc_info=True)

    pre = runpod_preflight.evaluate(
        connected=session.is_connected(),
        network_volume_id=session.network_volume_id,
        ssh_key_present=bool(_runpod_client_keys()),
        stock=stock,
        n_atoms=n_atoms,
    )
    if not pre.ok:
        raise HTTPException(400, runpod_preflight.blocking_reason(pre))

    try:
        runpod_supervisor.start_job(
            job,
            _workspace(),
            client=session.require(),
            network_volume_id=session.network_volume_id,
            client_keys=_runpod_client_keys(),
        )
    except RuntimeError as exc:  # unsizable system / unreadable package
        raise HTTPException(400, str(exc)) from exc

    job.status = MdStatus.running
    job.error = None
    job.failure_kind = None
    job.user_stopped = False
    job.save(_workspace())
    return {"ok": True, "job_id": job.job_id, "status": "running", "target": "runpod"}


def _runpod_client_keys() -> Optional[list[str]]:
    """The SSH private key used to reach a pod.

    RunPod injects the PUBLIC keys registered in the account's Settings into every pod at
    creation. A key added to a *running* pod's authorized_keys dies with that pod, which
    is the classic "permission denied (publickey)" on the next launch.
    """
    key = Path.home() / ".ssh" / "id_ed25519"
    return [str(key)] if key.exists() else None


class SubmitRemoteRequest(BaseModel):
    """Submit a prepared job to a compute cluster (Alpine/SLURM)."""
    cluster_name: str = Field("alpine", description="Cluster profile name")
    resources: Optional[dict] = Field(
        None, description="Override the auto-recommended SLURM resources (partition/"
                          "cores/gpus/mem_gb/walltime/qos). Omit to auto-recommend.",
    )
    safety_factor: float = Field(1.5, gt=0.0, description="Walltime headroom multiplier")


def _size_prepared_job(
    job: MdJob, profile, safety_factor: float, partition: Optional[str] = None
) -> Optional[dict]:
    """Sizing + Phase-2 auto-recommendation for a prepared job.

    Returns ``{n_atoms, total_ns, measured_ns_per_day, resources}`` or ``None``
    when the job has no ``manifest.json`` yet (still preparing / never prepped).
    Shared by the submit path and the review-card preview endpoint.  ``partition``
    forces a specific partition (else auto-pick) — the review card passes it when
    the user picks one from the dropdown.
    """
    from backend.core import cluster_resources, cluster_throughput
    package_dir = job.package_dir(_workspace())
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text())
    n_atoms = cluster_resources.n_atoms_from_manifest(manifest)
    total_ns = cluster_resources.total_ns_from_manifest(manifest)
    # Resolve the partition first (forced or auto-pick) so we can look up the LEARNED
    # Alpine throughput for that exact partition + size bucket.  A learned value beats
    # both the local-GPU metrics (wrong hardware for a CPU target) and the size guess;
    # fall back to local metrics, then to the size-based guess inside recommend().
    chosen_partition = cluster_resources.recommend(
        profile, n_atoms=n_atoms, total_ns=total_ns, safety_factor=safety_factor,
        partition=partition,
    )["partition"]
    measured = cluster_throughput.lookup_throughput(
        _workspace(), cluster=profile.name, partition=chosen_partition, n_atoms=n_atoms,
    )
    if measured is None:
        measured = cluster_resources.latest_ns_per_day(package_dir / "output" / "metrics.jsonl")
    resources = cluster_resources.recommend(
        profile, n_atoms=n_atoms, total_ns=total_ns,
        measured_ns_per_day=measured, safety_factor=safety_factor,
        partition=chosen_partition,
    )
    return {
        "n_atoms": n_atoms,
        "total_ns": total_ns,
        "measured_ns_per_day": measured,
        "resources": resources,
    }


def _remote_resources(job: MdJob, profile, body: "SubmitRemoteRequest") -> dict:
    """Resolve the SLURM resources for a remote submit: an explicit override, or the
    Phase-2 auto-recommendation from the prepared package's sizing + any measured
    ns/day."""
    if body.resources:
        return body.resources
    sizing = _size_prepared_job(job, profile, body.safety_factor)
    if sizing is None:
        raise HTTPException(400, "Job is not prepared yet (no manifest.json) — cannot size resources.")
    return sizing["resources"]


@router.get("/md/jobs/{job_id}/remote-recommendation")
def md_job_remote_recommendation(
    job_id: str, cluster_name: str = "alpine", safety_factor: float = 1.5,
    partition: Optional[str] = None, current: bool = False,
) -> dict:
    """Preview the auto-recommended SLURM resources for a prepared job — read-only,
    no cluster connection needed. Drives the Phase-4 submit-review card so the user
    sees system size / total ns / partition / walltime / est. SU cost before submitting.

    ``partition`` (optional) forces a specific partition instead of the auto-pick —
    the review card sends it when the user changes the partition dropdown, so the
    whole resource set (kind/gpus/cores/qos/gres) is re-derived consistently.
    ``available_partitions`` in the response populates that dropdown.

    Returns ``{prepared: false, reason}`` while the package is still being built.
    """
    from backend.core import cluster_config

    job = _load_job(job_id)
    profiles = cluster_config.load_profiles(_workspace())
    profile = profiles.get(cluster_name)
    if profile is None:
        raise HTTPException(404, f"Unknown cluster profile {cluster_name!r}.")

    try:
        sizing = _size_prepared_job(job, profile, safety_factor, partition=partition)
    except ValueError as exc:  # unknown forced partition
        raise HTTPException(400, str(exc)) from exc
    # Resume review: seed the card with the job's CURRENT resources (e.g. the short
    # walltime it just ran) so the user reviews/edits what they actually used, rather
    # than a fresh auto-recommend.  Skipped when the user forces a partition (the
    # dropdown change re-sizes on that partition consistently, like the submit path).
    if current and partition is None and job.resources and sizing is not None:
        sizing = {**sizing, "resources": job.resources}
    available = [
        {"name": p.name, "kind": p.kind, "gpu_model": p.gpu_model}
        for p in profile.partitions
    ]
    if sizing is None:
        return {
            "prepared": False,
            "status": job.status.value,
            "available_partitions": available,
            "reason": "Job is still preparing — resources can be sized once the package is built.",
        }
    rec_partition = (sizing["resources"] or {}).get("partition", profile.default_partition)
    available_qos = [
        {"name": q.name, "max_walltime_h": q.max_walltime_h}
        for q in profile.qos_tiers_for_partition(rec_partition)
    ]
    return {
        "prepared": True,
        "cluster_name": cluster_name,
        "design_name": job.design_name,
        "status": job.status.value,
        "already_submitted": bool(job.slurm_job_id),
        "slurm_job_id": job.slurm_job_id,
        "available_partitions": available,
        "available_qos": available_qos,
        **sizing,
    }


def _record_submit_failure(job: MdJob, msg: str) -> None:
    """Persist a remote-submit failure onto the job so the UI reflects it.

    A failed submit leaves the job PREPARED and retryable (no slurm id), so we keep
    it ``queued`` — but record the error so it no longer looks like a clean, pending
    job (or, worse, shows a running spinner).  The frontend renders an Alpine job
    that is queued-with-no-slurm-id as "awaiting submit" and surfaces this error.
    """
    try:
        job.slurm_job_id = None
        job.error = f"Cluster submission failed: {msg}"
        job.save(_workspace())
    except Exception as exc:  # never mask the original submit error
        logger.warning("could not record submit failure on %s: %s", job.job_id, exc)


@router.post("/md/jobs/{job_id}/submit-remote")
async def submit_md_job_remote(job_id: str, body: SubmitRemoteRequest) -> dict:
    """Stage + submit a prepared job to a cluster (needs a live cluster session).

    The whole relaxation ladder runs as ONE sbatch on the compute node; the MD
    supervisor then polls SLURM and fetches results back locally on completion.
    """
    from backend.core import cluster_config, cluster_ssh, md_executor

    job = _load_job(job_id)
    if job.status in (MdStatus.preparing,):
        raise HTTPException(400, "Job is still preparing — wait for prep to finish.")
    if job.slurm_job_id:
        raise HTTPException(409, f"Job already submitted to the cluster as SLURM {job.slurm_job_id}.")

    mgr = cluster_ssh.get_manager()
    if not mgr.is_connected():
        raise HTTPException(409, "Not connected to a cluster — connect first (Duo).")

    profiles = cluster_config.load_profiles(_workspace())
    profile = profiles.get(body.cluster_name)
    if profile is None:
        raise HTTPException(404, f"Unknown cluster profile {body.cluster_name!r}.")

    resources = _remote_resources(job, profile, body)
    try:
        job = await md_executor.submit_job(
            job, _workspace(), profile=profile, resources=resources, conn=mgr,
        )
    except cluster_ssh.ClusterSSHError as exc:
        _record_submit_failure(job, f"Cluster transport error: {exc}")
        raise HTTPException(502, f"Cluster transport error: {exc}") from exc
    except (ValueError, RuntimeError) as exc:
        _record_submit_failure(job, str(exc))
        raise HTTPException(400, str(exc)) from exc
    return {
        "ok": True,
        "job": job.to_dict(),
        "slurm_job_id": job.slurm_job_id,
        "cluster_name": job.cluster_name,
        "resources": resources,
    }


class ResumeRemoteRequest(BaseModel):
    cluster_name: str = "alpine"
    # Reviewed/edited SLURM resources for the resumed run (e.g. a longer walltime
    # after a promising short run).  Omitted → keep the job's existing resources.
    resources: Optional[dict] = None


@router.post("/md/jobs/{job_id}/resume-remote")
async def resume_md_job_remote(job_id: str, body: ResumeRemoteRequest) -> dict:
    """Resume a timed-out remote job from its latest checkpoint (needs a live session).

    One-click Resume: the user reconnects (Duo) and clicks Resume on a job that hit a
    walltime TIMEOUT.  NADOC regenerates the sbatch (completed segments skip, the
    interrupted one continues from its NAMD checkpoint) and resubmits as a new SLURM
    job — same job row, ``resubmit_count`` bumped, prior attempts kept in
    ``resume_history``.
    """
    from backend.core import cluster_config, cluster_ssh, md_executor

    job = _load_job(job_id)
    if job.execution_target != "alpine":
        raise HTTPException(400, "Not a cluster job.")
    if not job.resumable:
        raise HTTPException(400, "Job is not in a resumable (timed-out) state.")
    if not job.remote_scratch_dir:
        raise HTTPException(400, "Job has no remote scratch dir to resume from.")

    mgr = cluster_ssh.get_manager()
    if not mgr.is_connected():
        raise HTTPException(409, "Not connected to a cluster — connect first (Duo).")

    profiles = cluster_config.load_profiles(_workspace())
    profile = profiles.get(body.cluster_name or job.cluster_name or "alpine")
    if profile is None:
        raise HTTPException(404, f"Unknown cluster profile {body.cluster_name!r}.")

    try:
        job = await md_executor.resume_job(
            job, _workspace(), profile=profile, resources=body.resources, conn=mgr,
        )
    except cluster_ssh.ClusterSSHError as exc:
        raise HTTPException(502, f"Cluster transport error: {exc}") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "job": job.to_dict(), "slurm_job_id": job.slurm_job_id}


class RefitRequest(BaseModel):
    """Settings to override when re-running a failed job (all optional).

    The "Fix" popup sends whichever apply to the diagnosed failure: a water-shell
    carve for a VRAM downsize, force_soft for an instability, or none to retry.
    """
    water_shell_nm: Optional[float] = Field(None, ge=0.0)
    force_soft: Optional[bool] = Field(None)
    minimize_steps: Optional[int] = Field(None, ge=100)


# Failure kind → the remedy the "Fix" popup offers.
_REMEDY_BY_KIND = {
    "vram_oom": "downsize",     # refit with a water-shell carve sized to the GPU
    "host_oom": "retry",        # host pinned-RAM alloc failed — free RAM & resume
    "instability": "gentle",    # refit with the soft integrator across the ladder
    "gpu_error": "retry",       # resume — often a transient GPU/driver state
    # A pinned-timestep conflict is a CONFIG decision, not something the server may
    # silently repair — offering a one-click remedy here would recreate the downgrade
    # this failure exists to prevent. The popup explains; the user chooses.
    "timestep_pinned": "none",
    "other": "none",            # show the log; no automatic remedy
}


def _failed_log_excerpt(job: MdJob, max_lines: int = 24) -> Optional[str]:
    """Tail of the most recent package log, for the popup to display."""
    pkg = job.package_dir(_workspace())
    if not pkg.exists():
        return None
    logs = sorted(pkg.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return None
    try:
        lines = logs[0].read_text(errors="replace").splitlines()
    except OSError:
        return None
    return "\n".join(lines[-max_lines:])


def _fix_advice(job: MdJob) -> dict:
    """Diagnose any failed job and describe the remedy the UI should offer.

    For a VRAM OOM this includes the downsize recommendation (heavy geometry
    compute); other kinds just carry the classification + log excerpt.  Call via
    run_in_threadpool.
    """
    kind = job.failure_kind or "other"
    if kind == "vram_oom":
        out = _vram_advice(job)
    else:
        out = {
            "job_id": job.job_id,
            "is_vram_failure": False,
            "failure_kind": kind,
            "error": job.error,
            "vram_mb": detect_vram_mb(job.devices),
        }
        prof = (package_solvation_profile(job.package_dir(_workspace()), job.name_stem)
                if job.name_stem else None)
        out["current_water_shell_nm"] = (prof or {}).get("current_water_shell_nm")

    out["failure_kind"] = kind
    out["remedy"] = _REMEDY_BY_KIND.get(kind, "none")
    if kind == "vram_oom" and not out.get("feasible"):
        out["remedy"] = "none"   # can't downsize enough for this GPU
    out["log_excerpt"] = _failed_log_excerpt(job)
    return out


def _vram_advice(job: MdJob) -> dict:
    """Build the VRAM diagnosis + downsize recommendation for a job (blocking).

    Runs the geometry estimate, so call via run_in_threadpool.
    """
    vram_mb = detect_vram_mb(job.devices)
    profile = (
        package_solvation_profile(job.package_dir(_workspace()), job.name_stem)
        if job.name_stem else None
    )
    out: dict = {
        "job_id": job.job_id,
        "is_vram_failure": job.failure_kind == "vram_oom",
        "failure_kind": job.failure_kind,
        "error": job.error,
        "vram_mb": vram_mb,
        "vram_detected": vram_mb is not None,
        "profile_available": profile is not None,
        "current_water_shell_nm": (profile or {}).get("current_water_shell_nm"),
    }
    if profile is None or vram_mb is None:
        return out
    out.update(recommend_downsize(
        dna_xyz_nm = profile["dna_xyz_nm"],
        box_nm     = profile["box_nm"],
        full_water = profile["full_water"],
        dna_atoms  = profile["dna_atoms"],
        ion_atoms  = profile["ion_atoms"],
        vram_mb    = vram_mb,
    ))
    return out


@router.get("/md/jobs/{job_id}/fix-advice")
async def fix_advice(job_id: str) -> dict:
    """Diagnose a failed job and describe the remedy the "Fix" popup should offer.

    Covers VRAM out-of-memory (→ downsize), first-step instability (→ gentler
    relaxation), GPU/driver errors (→ retry), and anything else (→ show the log).
    """
    job = _load_job(job_id)
    return await run_in_threadpool(_fix_advice, job)


@router.post("/md/jobs/{job_id}/refit")
async def refit_md_job(job_id: str, body: RefitRequest) -> dict:
    """Create a new job from a failed one's provenance, with adjusted settings.

    Reuses the original design source / oxDNA seed and prep settings, overriding
    whichever of ``water_shell_nm`` / ``force_soft`` / ``minimize_steps`` were sent
    (a water-shell carve also forces the ladder to NVT downstream).
    """
    old = _load_job(job_id)
    if not (old.prep_params or old.design_source_path
            or old.seed_oxdna_job_id or old.seed_mrdna_job_id or old.seed_blade_job_id):
        raise HTTPException(400, "Cannot refit: original job has no design provenance.")

    try:
        find_namd(); find_gmx()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))

    # Reconstruct the original request, apply the sent overrides, backfill provenance.
    params = dict(old.prep_params or {})
    if body.water_shell_nm is not None:
        params["water_shell_nm"] = body.water_shell_nm
    if body.force_soft is not None:
        params["force_soft"] = body.force_soft
    if body.minimize_steps is not None:
        params["minimize_steps"] = body.minimize_steps
    params.setdefault("protocol", old.protocol)
    params.setdefault("threads", old.threads)
    params.setdefault("devices", old.devices)
    params.setdefault("design_source_path", old.design_source_path)
    params.setdefault("oxdna_job_id", old.seed_oxdna_job_id)
    params.setdefault("mrdna_job_id", old.seed_mrdna_job_id)
    params.setdefault("blade_job_id", old.seed_blade_job_id)
    valid = {k: v for k, v in params.items() if k in CreateJobRequest.model_fields}
    new_body = CreateJobRequest(**valid)

    seeded = bool(new_body.oxdna_job_id or new_body.mrdna_job_id or new_body.blade_job_id)
    if seeded:
        try:
            if new_body.oxdna_job_id:
                from backend.core.oxdna_runner import assert_namd_seed_available  # noqa: PLC0415
                await run_in_threadpool(assert_namd_seed_available, new_body.oxdna_job_id, _workspace())
            elif new_body.mrdna_job_id:
                from backend.core.mrdna_runner import assert_mrdna_namd_seed_available  # noqa: PLC0415
                await run_in_threadpool(assert_mrdna_namd_seed_available, new_body.mrdna_job_id, _workspace())
            else:
                from backend.core.blade_runner import assert_blade_namd_seed_available  # noqa: PLC0415
                await run_in_threadpool(assert_blade_namd_seed_available, new_body.blade_job_id, _workspace())
        except FileNotFoundError as exc:
            raise HTTPException(400, str(exc))
        design = None
        name = old.design_name or "design"
        size_factor = 1.0
    else:
        design = _load_design_for_refit(new_body.design_source_path)
        if design is None:
            raise HTTPException(
                400,
                "Cannot refit: original design could not be reloaded "
                f"({new_body.design_source_path!r}).",
            )
        if _sequenced_base_count(design) == 0:
            raise HTTPException(400, _NO_SEQUENCE_MSG)
        name = (design.metadata.name or "design").replace(" ", "_")
        size_factor = design_size_factor(design)

    job = _spawn_prep_job(new_body, design=design, seeded=seeded, name=name,
                          size_factor=size_factor, parent_job_id=job_id)
    logger.info("refit %s → new job %s (water_shell_nm=%.2f force_soft=%s)",
                job_id, job.job_id, new_body.water_shell_nm, new_body.force_soft)
    return {"ok": True, "job_id": job.job_id, "refit_from": job_id,
            "water_shell_nm": new_body.water_shell_nm, "force_soft": new_body.force_soft}


def _load_design_for_refit(source_path: Optional[str]):
    """Reload a Design for a non-seeded refit from its workspace source path."""
    from backend.core.models import Design  # noqa: PLC0415

    if source_path:
        p = (_workspace() / source_path)
        if p.exists():
            try:
                return Design.from_json(p.read_text())
            except (OSError, ValueError):
                pass
    # Fall back to the active design session, if any.
    try:
        return design_state.get_or_404()
    except HTTPException:
        return None


def _md_run_design(job):
    """The design a job's trajectory must be DISPLAYED against — its own frozen
    snapshot (walking the parent chain), else its recorded source ``.nadoc``.  Returns
    None when neither is resolvable (the caller then falls back to the open design).

    Unlike ``_load_design_for_refit`` this deliberately does NOT fall back to the active
    session: mapping a run onto whatever design happens to be open is the exact bug that
    scrambles the P-atom→(helix,bp) assignment into cross-structure streaks."""
    snap = _md_snapshot_design(job)
    if snap is not None:
        return snap
    sp = getattr(job, "design_source_path", None)
    if sp:
        from backend.core.models import Design  # noqa: PLC0415
        p = _workspace() / sp
        if p.exists():
            try:
                return Design.from_json(p.read_text())
            except (OSError, ValueError):
                pass
    return None


def md_display_design_for_job(job_id: str):
    """Resolve a job's own display design by id (for the live-Display WebSocket in
    ws.py).  Returns ``(design_or_None, design_name_or_None)``: the design is None when
    it can't be resolved (the WS then falls back to the design payload it was sent); the
    name is the job's recorded ``design_name`` (used in the mismatch-guard message even
    when the design itself couldn't be loaded)."""
    try:
        job = _load_job(job_id)
    except Exception:  # noqa: BLE001
        return None, None
    return _md_run_design(job), getattr(job, "design_name", None)


@router.post("/md/jobs/{job_id}/stop")
async def stop_md_job(job_id: str) -> dict:
    """Cancel a running job."""
    job = _load_job(job_id)

    # Mark as user-stopped so the startup/supervisor auto-resume leaves it alone.
    job.user_stopped = True
    job.save(_workspace())

    # ── RunPod: cancel the task AND destroy the pod ───────────────────────────
    # MUST come before the `!= "local"` branch below, which is the Alpine scancel path.
    # A RunPod job falling into it would find no cluster session, return "stopped" — and
    # LEAVE THE POD RUNNING, billing indefinitely with nothing watching it.
    if job.execution_target == "runpod":
        from backend.api import routes_runpod
        from backend.core import runpod_supervisor

        session = routes_runpod._SESSION  # noqa: SLF001
        await runpod_supervisor.stop_job(
            job_id, client=session.client if session.is_connected() else None
        )
        pod_id = job.runpod_pod_id
        job.status = MdStatus.stopped
        job.error = None
        job.runpod_pid = None
        job.save(_workspace())
        if pod_id and not session.is_connected():
            # We could not reach RunPod to confirm the kill. Say so loudly — a surviving
            # pod is a silent bill, and the user can terminate it from the pods list.
            return {
                "ok": True,
                "job_id": job_id,
                "status": "stopped",
                "warning": (
                    f"Not connected to RunPod — could not confirm pod {pod_id} was "
                    f"destroyed. Reconnect and check the pods list; a live pod is billing."
                ),
            }
        return {"ok": True, "job_id": job_id, "status": "stopped"}

    # Remote (Alpine/SLURM) jobs: scancel over the live session (this endpoint runs
    # on the main loop the asyncssh connection is bound to).
    if job.execution_target != "local":
        from backend.core import cluster_ssh, md_executor
        mgr = cluster_ssh.get_manager()
        if not mgr.is_connected():
            # Can't scancel a disconnected session — but DON'T silently leave the SLURM
            # job running (it would keep burning SUs while the UI reads "stopped").  Defer
            # the cancel: mark stopped locally + set pending_scancel so the next reconnect
            # (poll_remote_jobs) issues the scancel.  Only meaningful once submitted.
            if job.slurm_job_id:
                job.pending_scancel = True
            apply_user_stop(job)
            job.save(_workspace())
            msg = ("Cluster not connected — marked stopped locally; the SLURM job will be "
                   "cancelled automatically when you reconnect."
                   if job.slurm_job_id else
                   "Cluster not connected — marked stopped locally (job was not submitted yet).")
            return {"ok": True, "message": msg, "pending_scancel": bool(job.slurm_job_id)}
        try:
            issued = await md_executor.cancel_job(job, conn=mgr)
        except cluster_ssh.ClusterSSHError as exc:
            raise HTTPException(502, f"Cluster transport error: {exc}") from exc
        job.pending_scancel = False
        apply_user_stop(job)
        job.save(_workspace())
        return {"ok": True, "job_id": job_id,
                "status": "cancelled" if issued else "stopped",
                "slurm_job_id": job.slurm_job_id}

    cancelled = stop_job(job_id, _workspace())
    if not cancelled:
        # Not in our task registry — job may have completed or never started
        if job.status == MdStatus.running:
            apply_user_stop(job)
            job.save(_workspace())
        return {"ok": True, "message": "Job was not actively running"}

    return {"ok": True, "job_id": job_id, "status": "stopping"}


class EarlyStopRequest(BaseModel):
    enabled: bool = True


@router.post("/md/jobs/{job_id}/early-stop")
async def toggle_md_early_stop(job_id: str, body: EarlyStopRequest) -> dict:
    """Flip the relaxation early-stop accelerator on a job WITHOUT relaunching.

    If the job is running, the runner picks the new value up at its next chunk
    boundary; if idle, it's persisted for the next start/resume."""
    _load_job(job_id)   # 404s if the job doesn't exist
    val = set_early_stop(job_id, body.enabled, _workspace())
    return {"ok": True, "job_id": job_id, "early_stop_relax": val,
            "running": is_running(job_id)}


@router.get("/md/jobs/{job_id}/health")
async def get_md_job_health(job_id: str) -> list[dict]:
    """Return all health.jsonl records for the job."""
    job = _load_job(job_id)
    health_path = job.package_dir(_workspace()) / "output" / "health.jsonl"
    return _jsonl_records(health_path)


@router.get("/md/jobs/{job_id}/metrics")
async def get_md_job_metrics(job_id: str) -> list[dict]:
    """Return all metrics.jsonl records for the job."""
    job = _load_job(job_id)
    metrics_path = job.package_dir(_workspace()) / "output" / "metrics.jsonl"
    return _jsonl_records(metrics_path)


@router.get("/md/namd-available")
async def namd_available() -> dict:
    """Check whether NAMD3 and GROMACS are accessible."""
    try:
        namd_path = find_namd()
        namd_ok = True
    except RuntimeError:
        namd_path = None
        namd_ok = False

    try:
        gmx_path = find_gmx()
        gmx_ok = True
    except RuntimeError:
        gmx_path = None
        gmx_ok = False

    return {
        "available":      namd_ok and gmx_ok,
        "namd_available": namd_ok,
        "namd_path":      namd_path,
        "gmx_available":  gmx_ok,
        "gmx_path":       gmx_path,
        "recommended_threads": default_threads(),
    }


@router.get("/md/gpu-status")
async def gpu_status(devices: str = "0") -> dict:
    """Report external GPU-compute contention before the user starts a run.

    Flags a background process (e.g. an experiment's NAMD, a manual GROMACS run)
    holding the GPU, so the panel can warn before a second run OOMs the card.
    This app's own running NAMD jobs are excluded — the concurrent-job guard
    covers those.  Never throws: returns ``available:False`` if nvidia-smi is
    absent or the query fails.
    """
    from backend.core.md_vram import detect_gpu_activity, gpu_contention_summary  # noqa: PLC0415
    from backend.core.namd_runner import active_namd_pids  # noqa: PLC0415

    activity = await run_in_threadpool(detect_gpu_activity, devices)
    return gpu_contention_summary(activity, own_pids=active_namd_pids())


@router.get("/md/optimize-advanced/hardware")
async def optimize_advanced_hardware(devices: str = "0") -> dict:
    """GPU / RAM / core facts for this host — the FAST first stage of ⚡ Optimize.

    Split from the main call (which spends ~26 s building the design's heavy-atom
    model) so the panel's progress bar reports a real stage boundary instead of a
    fabricated animation.  Needs no design.
    """
    from backend.core.md_optimize import probe_hardware  # noqa: PLC0415

    return await run_in_threadpool(probe_hardware, devices)


@router.get("/md/optimize-advanced")
async def optimize_advanced(
    devices: str = "0",
    padding_nm: float = 1.2,
    minimize_steps: int = 10_000,
) -> dict:
    """Recommend Advanced-card settings for the active design on THIS machine.

    Backs the Advanced card's ⚡ Optimize button.  Read-only: it returns a proposal
    plus its rationale and caveats; the panel applies it only after the user confirms.
    Sizing the system runs a coarse geometric estimate (no GROMACS), so it is fast.
    """
    from backend.core.md_optimize import recommend_advanced  # noqa: PLC0415

    design = design_state.get_or_404()
    return await run_in_threadpool(
        recommend_advanced, design,
        devices=devices, padding_nm=padding_nm, minimize_steps=minimize_steps,
    )


# ── Molecular Dynamics load ────────────────────────────────────────────────────


@router.get("/md/browse")
def md_browse(dir: str = "", ext: str = "") -> dict:
    """
    List server-side filesystem entries for the MD file picker.

    Parameters
    ----------
    dir : absolute directory path to list (empty → user home directory)
    ext : comma-separated extensions to filter files (e.g. ".gro,.tpr")
          Empty = show all non-hidden files
    """
    from pathlib import Path

    base = Path(dir).resolve() if dir else Path.home()
    exts = {e.strip().lower() for e in ext.split(",") if e.strip()} if ext else set()

    entries: list[dict] = []

    # Parent navigation
    parent = base.parent
    if parent != base:
        entries.append({"name": "..", "path": str(parent), "type": "dir", "size": 0})

    try:
        items = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return {"path": str(base), "entries": entries}

    for p in items:
        if p.name.startswith("."):
            continue
        try:
            if p.is_dir():
                entries.append({"name": p.name, "path": str(p), "type": "dir", "size": 0})
            elif not exts or p.suffix.lower() in exts:
                entries.append({
                    "name": p.name,
                    "path": str(p),
                    "type": "file",
                    "size": p.stat().st_size,
                })
        except (PermissionError, OSError):
            continue

    return {"path": str(base), "entries": entries}


# ══ MD job PIPELINE / CHAIN executor (P2) ═══════════════════════════════════════
# Run an MdPipeline's stages back-to-back unattended: each stage is a production child
# seeded from the previous stage's output; on failure the chain halts and is resumable
# from the failed stage.  The engine-agnostic state machine lives in
# ``backend.core.md_chain_executor``; this is the NAMD spawn/status adapter + the
# create/list/resume routes + the supervisor driver (`advance_chains`).

def _chain_job_status(job_id: Optional[str]) -> str:
    """Map a chain stage's job status onto the executor's running/completed/failed vocab.

    Engine-agnostic: a stage's realised job is a NAMD ``MdJob`` OR an oxDNA job (the two
    stores share no id space — uuids), so resolve whichever owns ``job_id``. NAMD first
    (the common case); on a miss, fall back to the oxDNA store."""
    if not job_id:
        return "failed"
    try:
        job = _load_job(job_id)
    except HTTPException:
        return _oxdna_chain_job_status(job_id)
    if job.status == MdStatus.completed:
        return "completed"
    if job.status in (MdStatus.failed, MdStatus.stopped):
        return "failed"
    return "running"


def _oxdna_chain_job_status(job_id: str) -> str:
    """Status of an oxDNA chain stage's job, in the executor's vocabulary."""
    from backend.api.routes_oxdna import _load_job as _load_oxdna_job  # noqa: PLC0415
    from backend.core.oxdna_job import OxdnaStatus  # noqa: PLC0415
    try:
        job = _load_oxdna_job(job_id)  # already reconciles status from disk
    except HTTPException:
        return "failed"
    if job.status == OxdnaStatus.completed:
        return "completed"
    if job.status in (OxdnaStatus.failed, OxdnaStatus.stopped):
        return "failed"
    return "running"


# Protocol names that mark a stage as a structure-CREATING relaxation (a chain root that
# has no upstream job to seed from), vs a production restart.
_RELAX_PROTOCOLS = frozenset({"relax", "relaxation", "equilibration", "equilibrate"})


def _is_relax_protocol(protocol: Optional[str]) -> bool:
    return (protocol or "").lower() in _RELAX_PROTOCOLS


async def _chain_spawn(ctx: _chain.SpawnContext) -> str:
    """Realise one chain stage as a child job.

    Two hop kinds, chosen by :func:`md_pipeline.cross_engine_seed`:

    * **Same-engine (NAMD→NAMD)** — the common case, reuses ``spawn_md_production``, which
      seeds a production child from ANY completed NAMD job (relaxation OR production) by
      restarting its equilibrated ``.coor/.xsc`` (no coordinate reconstruction).  Stage 0's
      parent is the chain root; stage N's parent is the previous stage's realised child.

    * **Cross-engine (oxDNA/mrDNA→NAMD)** — P3.  The upstream coarse frame has no NAMD
      checkpoint to restart, so the stage instead reconstructs a fresh atomistic start
      structure from the upstream job's relaxed coordinates via the create-time seed hop
      (``create_md_job`` with ``oxdna_job_id`` / ``mrdna_job_id`` → ``build_namd_seed`` /
      ``build_namd_seed_from_mrdna``, where the nm/sim-unit/Ångström conversion already
      lives).  The stage's field/anchors ride the same ``CreateJobRequest`` the launch card
      uses.  A create seeded from a still-downloading remote frame raises (fast 400), which
      the supervisor treats as a transient precondition and retries (bounded).

    Run target / length flow from the stage spec; a local child autostarts, an alpine child
    queues for the submit-review card."""
    plan = ctx.plan
    if ctx.parent_job_id is None:
        # Fresh-relax root: no upstream job — CREATE the initial structure from the active
        # design via a relaxation for this engine (the "Queue Relax" stage).
        return await _spawn_fresh_relax(plan)
    if plan.engine == "oxdna":
        # Same-engine oxDNA hop: a production/field child branched off the completed
        # previous oxDNA stage (or an existing completed oxDNA root job).
        return await _spawn_oxdna_child(ctx.parent_job_id, plan)
    seed = cross_engine_seed(plan, ctx.parent_job_id)  # None ⇒ same-engine checkpoint hop
    if seed is not None:
        forces = ctx.forces or {}
        # The cross-engine hop goes through the RELAXATION-creation endpoint (it builds +
        # solvates + relaxes a fresh atomistic seed — there is no NAMD checkpoint to
        # restart), so its protocol must be a relaxation preset.  A pipeline stage's
        # protocol defaults to "production" (meaningful only for the same-engine restart
        # path, which uses ProductionRunRequest); map any non-relaxation name onto the
        # default relaxation preset so a default oxDNA/mrDNA→NAMD stage isn't rejected.
        create_protocol = (
            plan.protocol if plan.protocol in SUPPORTED_PROTOCOLS
            else EQUILIBRIUM_AWARE_PROTOCOL)
        body = CreateJobRequest(
            protocol=create_protocol,
            autostart=(plan.run_target == "local"),
            execution_target=plan.run_target,
            cluster_name=plan.cluster_name,
            field=forces.get("field"),
            anchors=forces.get("anchors"),
            design_source_path=plan.design_source_path,
            **{seed.seed_field: seed.seed_job_id},
        )
        result = await create_md_job(body)
        return result["job_id"]
    body = ProductionRunRequest(
        steps=plan.steps,
        length_ns=plan.length_ns,
        autostart=(plan.run_target == "local"),
        execution_target=plan.run_target,
        cluster_name=plan.cluster_name,
    )
    result = await spawn_md_production(ctx.parent_job_id, body)
    return result["job"]["job_id"]


async def _spawn_fresh_relax(plan: "StagePlan") -> str:
    """Stage 0 of a rootless chain: create the initial structure from the ACTIVE design
    via a fresh relaxation for this engine (no upstream job to seed from).

    * oxDNA — a 3-stage relaxation (``create_oxdna_job``) carrying the stage's hard
      surface + anchors (an oxDNA relaxation excludes the E-field by design — a
      field-relaxed structure isn't how it settles);
    * NAMD — a fresh atomistic relaxation (``create_md_job``) carrying field + anchors.
    """
    forces = plan.forces or {}
    if plan.engine == "oxdna":
        from backend.api.routes_oxdna import (  # noqa: PLC0415
            CreateOxdnaJobRequest, create_oxdna_job,
        )
        surface = forces.get("surface")
        anchors = forces.get("anchors") or []
        body = CreateOxdnaJobRequest.model_validate({
            "autostart": plan.run_target == "local",
            "surface": surface,
            "anchors": anchors,
            "design_source_path": plan.design_source_path,
        })
        result = await create_oxdna_job(body)
        job_id = result.get("job_id")
        if not job_id or result.get("status") == "failed":
            raise RuntimeError(f"oxDNA relax spawn failed: {result.get('error') or 'no job id'}")
        return job_id
    body = CreateJobRequest(
        protocol=EQUILIBRIUM_AWARE_PROTOCOL,
        autostart=(plan.run_target == "local"),
        execution_target=plan.run_target,
        cluster_name=plan.cluster_name,
        field=forces.get("field"),
        anchors=forces.get("anchors"),
        design_source_path=plan.design_source_path,
    )
    result = await create_md_job(body)
    return result["job_id"]


async def advance_vacuum_prestages(workspace: Path) -> list[str]:
    """Spawn the solvated run for every vacuum pre-stage that has finished.

    Driven by the MD supervisor loop, beside :func:`advance_chains`.  The vacuum job is
    an ordinary MdJob, so it already gets PID tracking, stop, resume and failure
    classification for free; all this adds is the hand-off.

    Idempotent: the follow-up id is recorded on the vacuum job before returning, and a
    job that already has one is skipped.  A FAILED vacuum stage is left alone — the
    idealised build is still there, so the user can retry or skip the pre-stage rather
    than silently getting an unrelaxed run.
    """
    spawned: list[str] = []
    for job in MdJob.list_jobs(workspace):
        if job.run_kind != VACUUM_PRESTAGE_RUN_KIND:
            continue
        if job.status != MdStatus.completed:
            continue
        params = dict(job.prep_params or {})
        followup = params.get("vacuum_followup")
        if not followup or params.get("vacuum_followup_job_id"):
            continue
        try:
            body = CreateJobRequest.model_validate({
                **followup,
                "vacuum_job_id": job.job_id,
                # Belt and braces against a spawn loop: the follow-up must never itself
                # decide it wants a pre-stage.
                "skip_vacuum_prestage": True,
            })
            result = await create_md_job(body)
        except Exception as exc:  # noqa: BLE001 — one bad job must not stall the pass
            logger.exception("vacuum follow-up for %s failed to spawn", job.job_id)
            params["vacuum_followup_error"] = str(exc)
            job.prep_params = params
            job.save(workspace)
            continue
        child_id = result.get("job_id")
        params["vacuum_followup_job_id"] = child_id
        job.prep_params = params
        job.save(workspace)
        # Provenance both ways: the solvated job records where its coordinates came from.
        try:
            child = MdJob.load(child_id, workspace)
            child.seed_vacuum_job_id = job.job_id
            child.parent_job_id = job.job_id
            child.save(workspace)
        except Exception:  # noqa: BLE001 — provenance is not worth failing the spawn
            logger.warning("could not stamp vacuum provenance on %s", child_id)
        logger.info("vacuum pre-stage %s → solvated job %s", job.job_id, child_id)
        spawned.append(child_id)
    return spawned


async def _spawn_oxdna_child(parent_job_id: str, plan: "StagePlan") -> str:
    """A same-engine oxDNA hop: a consolidated production/field run branched off the
    completed previous oxDNA stage (``append_oxdna_run`` → a fresh child job seeded from
    the parent's relaxed conf), carrying the stage's field / surface / anchors."""
    from backend.api.routes_oxdna import RunRequest, append_oxdna_run  # noqa: PLC0415
    forces = plan.forces or {}
    run_body: dict = {"steps": plan.steps or 2_000_000}
    field = forces.get("field")
    if field and field.get("field_pN"):
        run_body["field"] = field
    if forces.get("surface"):
        run_body["surface"] = forces["surface"]
    if forces.get("anchors"):
        run_body["anchors"] = forces["anchors"]
    result = await append_oxdna_run(parent_job_id, RunRequest.model_validate(run_body))
    return result["job_id"]


# A stage spawn can fail on a TRANSIENT precondition — e.g. the previous stage's remote
# outputs haven't finished downloading yet, so its seed checkpoint isn't on disk.  Rather
# than dead-end the whole (unattended) chain on the first hiccup, the driver leaves the
# stage pending and retries on the next supervisor tick, halting only after this many
# consecutive failures (mirrors namd_runner's MAX_*_RESUMES bounded auto-resume).
_MAX_STAGE_SPAWN_ATTEMPTS = 3


async def advance_chains(workspace: Path) -> list[str]:
    """Drive every persisted chain by at most one transition (the MD supervisor pass).

    Reconcile the running stage against its job's status, then — if none is in flight —
    spawn the next stage.  A transient spawn failure leaves the stage pending for a bounded
    number of retries; past the cap the chain halts (resumable from that stage).  Returns
    the ids of chains whose state changed (so the supervisor can log them)."""
    touched: list[str] = []
    for chain in _chain.list_chains(workspace):
        if chain.status in (_chain.CHAIN_COMPLETED, _chain.CHAIN_FAILED):
            continue
        before = chain.to_dict()
        _chain.reconcile_running(chain, _chain_job_status)
        ctx = _chain.next_spawn(chain)
        if ctx is not None:
            try:
                # _chain_spawn must be all-or-nothing: it currently only raises on a
                # precondition BEFORE creating/starting the child, so the except path
                # below can safely assume no job was spawned (the invariant that keeps
                # "one stage runs at a time" intact — see spawn_md_production).
                # Mark the spawn unattended so the per-engine live-design guards stand
                # down (this stage seeds from the parent job's frozen state, not whatever
                # design is loaded — otherwise switching designs mid-run halts the chain).
                with _chain.unattended_chain_spawn():
                    job_id = await _chain_spawn(ctx)
            except Exception as exc:  # noqa: BLE001 — transient-tolerant bounded retry
                stage = chain.stages[ctx.stage_index]
                stage.spawn_attempts += 1
                logger.exception(
                    "chain %s stage %d spawn failed (attempt %d/%d)",
                    chain.chain_id, ctx.stage_index, stage.spawn_attempts,
                    _MAX_STAGE_SPAWN_ATTEMPTS)
                if stage.spawn_attempts >= _MAX_STAGE_SPAWN_ATTEMPTS:
                    stage.status = _chain.STAGE_FAILED
                    chain.status = _chain.CHAIN_FAILED
                    chain.error = (
                        f"stage {ctx.stage_index} spawn failed after "
                        f"{stage.spawn_attempts} attempts: {exc}")
                else:  # leave the stage pending — the next tick retries
                    chain.error = (
                        f"stage {ctx.stage_index} spawn attempt {stage.spawn_attempts} "
                        f"failed (will retry): {exc}")
            else:
                _chain.mark_spawned(chain, ctx.stage_index, job_id)
        if chain.to_dict() != before:
            _chain.save_chain(chain, workspace)
            touched.append(chain.chain_id)
    return touched


class ChainStageRequest(BaseModel):
    """One stage in a chain request (mirrors ``PipelineStage``)."""
    engine: str = Field(..., description="Engine for this stage, e.g. 'namd'")
    protocol: str = Field("production", description="Run protocol for the stage")
    field: Optional[dict] = Field(None, description="Shared E-field descriptor")
    anchors: Optional[list] = Field(None, description="Shared anchor-scope list")
    surface: Optional[dict] = Field(None, description="Shared surface/floor descriptor")
    run_target: str = Field("local", description="'local' or 'alpine'")
    cluster_name: Optional[str] = Field(None, description="Cluster for an alpine stage")
    length_ns: Optional[float] = Field(None, gt=0.0, le=100.0)
    steps: Optional[int] = Field(None, ge=100, le=50_000_000)
    label: Optional[str] = Field(None, description="Human label for the stage")


class CreateChainRequest(BaseModel):
    """Queue a multi-stage chain.

    Two rooting modes:

    * ``root_job_id`` set — the chain seeds stage 0 from that ALREADY-COMPLETED job's
      checkpoint (the "already ran a relax, now queue a series of productions" case);
    * ``root_job_id`` None — stage 0 is a *fresh relaxation* that CREATES the initial
      structure from the active design (the "Queue Relax → Queue Production" case). Its
      first stage must be a relaxation (``protocol == "relax"``).
    """
    root_job_id: Optional[str] = Field(
        None, description="Completed job whose checkpoint seeds stage 0; None = stage 0 is a fresh relax")
    root_engine: Optional[str] = Field(None, description="Engine of the root job")
    design_source_path: Optional[str] = Field(
        None, description="Workspace path of the active design — stamped onto spawned jobs so "
        "they appear in the per-design engine job list")
    stages: list[ChainStageRequest] = Field(..., description="Ordered stage specs")


@router.post("/md/chains")
async def create_md_chain(body: CreateChainRequest) -> dict:
    """Build + persist an ``MdPipeline`` chain, then spawn stage 0.  The MD supervisor
    advances the remaining stages unattended (stage N on stage N-1's completion).

    The root may be a completed NAMD job (same-engine seed) OR a completed oxDNA/mrDNA job
    (cross-engine seed — stage 0 rebuilds an atomistic model from the coarse relaxed frame,
    P3).  A CG root is validated by the SAME seed-available check the launch card uses
    (the frame exists on disk), not by loading it as an ``MdJob``."""
    if not body.stages:
        raise HTTPException(400, "A chain needs at least one stage.")
    # An unanchored uniform field on a production stage just drifts the whole structure
    # (COM drift); that's surfaced as a per-stage UI warning, not a launch block.
    if body.root_job_id is None:
        # Fresh-relax root: stage 0 CREATES the initial structure from the active design.
        # It must therefore be a relaxation — a production has nothing to seed from.
        if not _is_relax_protocol(body.stages[0].protocol):
            raise HTTPException(
                400, "A rootless chain's first stage must be a relaxation (it creates the "
                "initial structure); a production needs an upstream job to seed from.")
        root_engine = (body.root_engine or body.stages[0].engine or "namd").lower()
    else:
        root_engine = (body.root_engine or "namd").lower()
        if root_engine == "oxdna":
            from backend.core.oxdna_runner import assert_namd_seed_available  # noqa: PLC0415
            # A cross-engine oxDNA→NAMD root needs a NAMD seed frame; a same-engine
            # oxDNA→oxDNA production just restarts the completed oxDNA job's relaxed conf.
            if body.stages[0].engine != "oxdna":
                try:
                    await run_in_threadpool(assert_namd_seed_available, body.root_job_id, _workspace())
                except FileNotFoundError as exc:
                    raise HTTPException(400, str(exc))
        elif root_engine == "mrdna":
            from backend.core.mrdna_runner import assert_mrdna_namd_seed_available  # noqa: PLC0415
            try:
                await run_in_threadpool(assert_mrdna_namd_seed_available, body.root_job_id, _workspace())
            except FileNotFoundError as exc:
                raise HTTPException(400, str(exc))
        else:
            root = _load_job(body.root_job_id)  # 404 if missing
            if root.status != MdStatus.completed:
                raise HTTPException(
                    400, "The chain's root job must be a completed run to seed the first stage.")
    pipeline = MdPipeline(
        root_job_id=body.root_job_id,
        root_engine=root_engine,
        design_source_path=body.design_source_path,
        stages=[PipelineStage(**s.model_dump()) for s in body.stages],
    )
    chain_id = uuid.uuid4().hex[:12]
    chain = _chain.init_chain_run(pipeline, chain_id=chain_id)
    _chain.save_chain(chain, _workspace())
    # Kick stage 0 immediately so the chain is live before the first supervisor tick.
    await advance_chains(_workspace())
    return {"ok": True, "chain": _chain.load_chain(chain_id, _workspace()).to_dict()}


@router.get("/md/chains")
async def list_md_chains() -> dict:
    return {"chains": [c.to_dict() for c in _chain.list_chains(_workspace())]}


@router.get("/md/chains/{chain_id}")
async def get_md_chain(chain_id: str) -> dict:
    try:
        return {"chain": _chain.load_chain(chain_id, _workspace()).to_dict()}
    except FileNotFoundError:
        raise HTTPException(404, f"No chain {chain_id}.")


@router.post("/md/chains/{chain_id}/resume")
async def resume_md_chain(chain_id: str) -> dict:
    """Resume a HALTED chain from its failed stage (retry-only-failed) and re-advance."""
    try:
        chain = _chain.load_chain(chain_id, _workspace())
    except FileNotFoundError:
        raise HTTPException(404, f"No chain {chain_id}.")
    if chain.status != _chain.CHAIN_FAILED:
        raise HTTPException(400, "Only a halted (failed) chain can be resumed.")
    _chain.resume_chain(chain)
    _chain.save_chain(chain, _workspace())
    await advance_chains(_workspace())
    return {"ok": True, "chain": _chain.load_chain(chain_id, _workspace()).to_dict()}
