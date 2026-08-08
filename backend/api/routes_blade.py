"""
BLADE job routes — create, inspect, control, and display.

BLADE = box-free CHARMM36 + OBC2 implicit-solvent atomistic relax (see
``backend/core/blade_job.py``).  Structurally this is CanDo/SNUPI's sibling — one flat job
per run, same panel, same Run/Stop/Delete — but the compute is EXTERNAL: OpenMM in the
micromamba ``gpu`` env, reached through a detached worker.  That gives it two things the
in-process FEM engines don't have: a real availability probe (``/blade/available``) and a
killable subprocess.

MVP is ``mode="relax"``.  ``seed_namd`` (relax → solvate → NAMD equilibration) is reserved
and rejected at create time until it's wired.

All routes prefixed with /api.  Mounted in ``backend/api/main.py``.

Route summary
─────────────
POST   /blade/jobs                  create + run an implicit-solvent relax
GET    /blade/jobs                  list all jobs
GET    /blade/jobs/{id}             single job status
GET    /blade/jobs/{id}/progress    overall progress fraction + ETA
POST   /blade/jobs/{id}/start       start or resume a queued/stopped/failed job
POST   /blade/jobs/{id}/stop        stop a running job (group-kills the OpenMM grandchild)
DELETE /blade/jobs/{id}             delete job + generated files
GET    /blade/jobs/{id}/snapshot-geometry  full geometry of the job's OWN design snapshot
GET    /blade/jobs/{id}/display     the settled shape as {keys, frame} + the run summary
GET    /blade/jobs/{id}/trajectory  the relaxation trajectory for the scrubber
GET    /blade/jobs/{id}/error-log   failure log for the UI popup
GET    /blade/available             can a relax run here, and why not if not

There is deliberately no /rmsf, /deviation, /cylinders or /shape-source: those are FEM
products (an NMA eigensolve, an intended-shape comparison, axis tubes).  A relax has no
normal-mode basis, so exposing them would mean inventing numbers.

Display note: relaxed coordinates are Physical-layer only; they never mutate topology.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.api import state as design_state
from backend.api.assembly import _WORKSPACE_DIR
from backend.core.blade_job import BladeJob, BladeStatus, new_blade_job
from backend.core.blade_runner import (
    is_running,
    job_progress,
    load_display,
    prepare_blade_job,
    reconcile_blade_status,
    start_job,
    stop_job,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["blade"])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _workspace() -> Path:
    return _WORKSPACE_DIR


def _load_job(job_id: str) -> BladeJob:
    try:
        job = BladeJob.load(job_id, _workspace())
    except FileNotFoundError:
        raise HTTPException(404, f"BLADE job {job_id!r} not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Failed to load job {job_id}: {exc}")
    return reconcile_blade_status(job, _workspace())


def _current_fingerprint() -> "str | None":
    from backend.core.oxdna_staleness import oxdna_design_fingerprint

    design = design_state.get_design()
    if design is None:
        return None
    try:
        return oxdna_design_fingerprint(design)
    except Exception:  # noqa: BLE001
        return None


def _is_out_of_date(job: BladeJob, current_fp: "str | None") -> bool:
    from backend.core.oxdna_staleness import job_out_of_date

    return job_out_of_date(job.design_fingerprint, current_fp)


# ── Request models ────────────────────────────────────────────────────────────


class CreateBladeJobRequest(BaseModel):
    mode: str = Field(
        "relax",
        description="'relax' = implicit-solvent relaxation of the idealized "
        "geometry (the shipped mode). 'seed_namd' (relax → solvate → "
        "NAMD equilibration) is reserved and not yet implemented.",
    )
    correction: str = Field(
        "baseline",
        description="Force model: 'baseline' = pure CHARMM36 + OBC2 "
        "(training-free); 'unified' = baseline + the learned unified "
        "duplex+ssDNA ForceNet solvent correction.",
    )
    minimize_iters: int = Field(
        400, ge=0, le=20000, description="OpenMM L-BFGS minimization iteration cap."
    )
    langevin_ps: float = Field(
        3.0,
        gt=0.0,
        le=1000.0,
        description="Langevin settling time in picoseconds. 3 ps is the "
        "benchmarked default that produced a stable curved-6HB relax.",
    )
    nb_cutoff_A: float = Field(
        18.0,
        ge=8.0,
        le=50.0,
        description="CutoffNonPeriodic radius (Å). Keeps GBSA ~O(N) — the reason a "
        "40k-atom origami relaxes in minutes rather than hitting the "
        "O(N²) NoCutoff wall. Raising it is accuracy-for-time.",
    )
    temp_K: float = Field(
        300.0, ge=1.0, le=500.0, description="Langevin temperature (K)."
    )
    traj_frames: int = Field(
        60,
        ge=0,
        le=500,
        description="DCD frames captured across the Langevin leg (0 = no "
        "trajectory, just the relaxed structure).",
    )
    platform: str = Field(
        "CUDA",
        description="OpenMM platform. 'CUDA' uses the local card and is gated by "
        "the shared sim guard; 'CPU' never contends but measures "
        "~20× slower.",
    )
    uncertainty: bool = Field(
        False,
        description="Per-atom epistemic uncertainty overlay (EnsembleForceNet). "
        "NOT AVAILABLE YET — no ensemble checkpoint exists; "
        "forcenet_unified.pt is a single ForceNet. Rejected if set.",
    )
    autostart: bool = Field(True)
    design_source_path: Optional[str] = Field(
        None, description="Workspace path of the active design"
    )


# ── Create / list / status ────────────────────────────────────────────────────


@router.post("/blade/jobs")
async def create_blade_job(body: CreateBladeJobRequest) -> dict:
    """Prepare + run a new BLADE implicit-solvent relax from the active design."""
    design = design_state.get_or_404()
    if not design.helices:
        raise HTTPException(400, "Design has no helices to relax.")

    name = None
    if body.design_source_path:
        name = Path(body.design_source_path).stem or None
    name = (name or design.metadata.name or "design").replace(" ", "_")

    from backend.api import doc_context
    from backend.core.oxdna_staleness import (
        effective_feature_log_position,
        oxdna_design_fingerprint,
    )
    from backend.physics.oxdna_interface import _strand_nucleotide_order

    if body.mode != "relax":
        raise HTTPException(
            400,
            "Only mode='relax' is implemented. 'seed_namd' (relax → solvate → "
            "NAMD equilibration) is planned but not wired yet.",
        )
    # The learned correction and the uncertainty overlay are two different maturity levels, and
    # conflating them would be misleading.  The unified ForceNet checkpoint exists and is usable;
    # the ENSEMBLE (which is what per-atom epistemic uncertainty requires) has never been trained
    # or saved — forcenet_unified.pt is a single ForceNet.  Refuse rather than invent a scalar.
    if body.uncertainty:
        raise HTTPException(
            400,
            "Per-atom uncertainty needs an EnsembleForceNet checkpoint, and "
            "none exists yet (forcenet_unified.pt holds a single ForceNet). "
            "Train + save a K-member ensemble first.",
        )
    correction = (
        body.correction if body.correction in ("baseline", "unified") else "baseline"
    )
    platform = (body.platform or "CUDA").upper()
    if platform not in ("CUDA", "CPU"):
        raise HTTPException(
            400, f"Unknown platform {body.platform!r} — use 'CUDA' or 'CPU'."
        )

    # Refuse up front if the compute environment is missing, rather than letting the detached
    # worker die seconds in with a stack trace the panel can only show as a raw error.
    from backend.core.blade_runner import blade_available

    ok, reason = await run_in_threadpool(blade_available)
    if not ok:
        raise HTTPException(503, f"BLADE cannot run: {reason}")

    job = new_blade_job(
        design_name=name,
        mode=body.mode,
        correction=correction,
        minimize_iters=body.minimize_iters,
        langevin_ps=body.langevin_ps,
        nb_cutoff_A=body.nb_cutoff_A,
        temp_K=body.temp_K,
        traj_frames=body.traj_frames,
        platform=platform,
        uncertainty=False,
        n_nucleotides=len(_strand_nucleotide_order(design)),
        design_source_path=body.design_source_path,
        design_fingerprint=oxdna_design_fingerprint(design),
        feature_log_position=effective_feature_log_position(design),
        doc_id=doc_context.get_current_doc(),
    )
    job.status = BladeStatus.preparing
    job.save(_workspace())
    logger.info(
        "create_blade_job: job_id=%s design=%s mode=%s correction=%s platform=%s",
        job.job_id,
        name,
        body.mode,
        correction,
        platform,
    )

    try:
        await run_in_threadpool(prepare_blade_job, design, job, _workspace())
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "create_blade_job: prepare FAILED for %s: %s",
            job.job_id,
            exc,
            exc_info=True,
        )
        job.status = BladeStatus.failed
        job.error = f"Preparation failed: {exc}"
        job.save(_workspace())
        return job.to_dict()

    job.status = BladeStatus.queued
    job.save(_workspace())
    if body.autostart:
        try:
            start_job(job, _workspace())
        except RuntimeError as exc:
            # Sim guard refused. The job is prepared and valid — leave it queued with the reason
            # so the user can start it later (or pick CPU) instead of losing the preparation.
            job.error = str(exc)
            job.save(_workspace())
    return job.to_dict()


@router.get("/blade/jobs")
async def list_blade_jobs() -> list[dict]:
    from backend.core.design_disk_usage import dir_size_bytes_cached

    ws = _workspace()
    jobs = [reconcile_blade_status(j, ws) for j in BladeJob.list_jobs(ws)]
    current_fp = _current_fingerprint()
    out: list[dict] = []
    for j in jobs:
        d = j.to_dict()
        d["out_of_date"] = _is_out_of_date(j, current_fp)
        d["size_bytes"] = dir_size_bytes_cached(j.job_dir(ws))
        # A RUNNING job carries its live fraction + ETA so the ONE master progress bar in the unified
        # Jobs card advances during the run. Unlike the FEM engines this fraction is REAL — streamed
        # out of the OpenMM process — so the bar tracks actual work rather than a wall-clock guess.
        if d.get("status") == "running":
            try:
                from backend.core.blade_runner import job_progress

                p = job_progress(j, ws)
                d["progress_fraction"] = round(float(p.get("overall") or 0.0), 4)
                d["eta_seconds"] = p.get("eta_seconds")
                d["phase"] = p.get("phase")
                # Fine detail so a long relax visibly ticks; platform_used exposes a silent
                # CUDA->CPU fallback, which is a ~20x slowdown the user needs to see live.
                for k in ("step", "n_steps", "steps_per_s", "platform_used"):
                    if p.get(k) is not None:
                        d[k] = p[k]
            except Exception:  # noqa: BLE001 — progress is advisory, never sink the list
                pass
        out.append(d)
    return out


@router.get("/blade/jobs/{job_id}")
async def get_blade_job(job_id: str) -> dict:
    job = _load_job(job_id)
    d = job.to_dict()
    d["out_of_date"] = _is_out_of_date(job, _current_fingerprint())
    return d


@router.get("/blade/jobs/{job_id}/progress")
async def get_blade_progress(job_id: str) -> dict:
    job = _load_job(job_id)
    return job_progress(job, _workspace())


@router.get("/blade/jobs/{job_id}/error-log")
async def get_blade_error_log(job_id: str) -> dict:
    """Failure detail for the UI's 'Error log' popup."""
    job = _load_job(job_id)
    return {
        "job_id": job_id,
        "status": job.status.value,
        "error": job.error or "",
        "log": job.error or "(no error recorded)",
    }


# ── Control ───────────────────────────────────────────────────────────────────


@router.post("/blade/jobs/{job_id}/start")
async def start_blade_job(job_id: str) -> dict:
    job = _load_job(job_id)
    if is_running(job_id, _workspace()):
        return {"ok": True, "message": "Job already running"}
    if job.status in (BladeStatus.running, BladeStatus.completed):
        raise HTTPException(400, f"Job is {job.status.value} — cannot start")
    if job.stages:
        job.stages[0].status = "pending"
        job.stages[0].started_at = None
    job.status = BladeStatus.running
    job.error = None
    job.save(_workspace())
    try:
        start_job(job, _workspace())
    except RuntimeError as exc:
        # The sim guard refused (a heavy production sim owns the GPU).  Put the job back where
        # it was so the row doesn't sit falsely "running", and surface the reason + the fixes.
        job.status = BladeStatus.queued
        job.error = str(exc)
        job.save(_workspace())
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "job_id": job_id, "status": "running"}


@router.post("/blade/jobs/{job_id}/stop")
async def stop_blade_job(job_id: str) -> dict:
    job = _load_job(job_id)
    stopped = stop_job(job_id, _workspace())
    if not stopped:
        if job.status == BladeStatus.running:
            job.status = BladeStatus.stopped
            job.save(_workspace())
        return {"ok": True, "message": "Job was not actively running"}
    return {"ok": True, "job_id": job_id, "status": "stopping"}


@router.delete("/blade/jobs/{job_id}")
async def delete_blade_job(job_id: str) -> dict:
    ws = _workspace()
    job = _load_job(job_id)
    if is_running(job_id, ws) or job.status == BladeStatus.running:
        raise HTTPException(400, "Stop the BLADE job before deleting it")
    from backend.core.job_archive import purge_index_entry

    jd = job.job_dir(ws)
    if jd.exists():
        shutil.rmtree(jd)
    purge_index_entry(ws, "blade_jobs", job.job_id)
    return {"ok": True, "job_id": job_id}


# ── Display ───────────────────────────────────────────────────────────────────


@router.get("/blade/jobs/{job_id}/snapshot-geometry")
async def get_blade_snapshot_geometry(job_id: str) -> dict:
    """The full geometry of the job's OWN design snapshot — the topology the design had
    when the analysis was run, not live editor state.  The display modes render THIS
    (hiding the live model) and then overlay the FEM-predicted shape on it.

    Same shape as ``GET /design/geometry`` plus the snapshot ``design`` object:
    ``{ready, design, nucleotides:[...], helix_axes:[{helix_id,start,end,...}]}``.
    """
    from backend.core.deformation import (
        _apply_ovhg_rotations_to_axes,
        deformed_helix_axes,
    )
    from backend.core.design_geometry import _geometry_for_helices
    from backend.core.blade_runner import _load_snapshot_design

    job = _load_job(job_id)
    design = _load_snapshot_design(job.job_dir(_workspace()))
    if design is None or not design.helices:
        return {
            "job_id": job.job_id,
            "ready": False,
            "nucleotides": [],
            "helix_axes": [],
        }

    def _compute() -> tuple[list, list]:
        nucleotides = _geometry_for_helices(design, None, junction_balance=True)
        axes = deformed_helix_axes(design)
        _apply_ovhg_rotations_to_axes(design, axes, nucleotides)
        return nucleotides, axes

    nucleotides, axes = await run_in_threadpool(_compute)
    return {
        "job_id": job.job_id,
        "ready": True,
        "design": design.model_dump(mode="json"),
        "nucleotides": nucleotides,
        "helix_axes": axes,
    }


@router.get("/blade/jobs/{job_id}/display")
async def get_blade_display(job_id: str) -> dict:
    """The RELAXED shape as a single trajectory frame the renderer can overlay.

    BLADE's native output is atomistic, but the display layer thinks in nucleotides, so the
    relaxed shape is served as ``{keys, frame}`` in the same encoding as ``/trajectory`` — the
    frontend runs it through ``framesToUpdates`` and hands the result to ``applyFemPositions``,
    exactly as it does for a trajectory frame.  The frame is the LAST one of the relax, i.e.
    the settled structure.

    Also carries ``summary`` (rmsd moved, Rg before/after, platform, wall time) for the metrics
    card, and ``relaxed_pdb`` — the path to the full all-atom result, which is what the
    NAMD-seed hook consumes.  Physical-layer only; never written back into topology.
    """
    from backend.core.blade_runner import load_trajectory

    job = _load_job(job_id)
    jd = job.job_dir(_workspace())
    cached = load_display(jd)
    if not cached:
        return {"job_id": job.job_id, "ready": False, "keys": [], "frame": []}
    traj = load_trajectory(jd)
    keys = (traj or {}).get("keys") or []
    frames = (traj or {}).get("frames") or []
    return {
        "job_id": job.job_id,
        "ready": bool(keys and frames),
        "status": job.status.value,
        "keys": keys,
        "frame": frames[-1] if frames else [],
        "n_nucleotides": (traj or {}).get("n_nucleotides", 0),
        "n_atoms": cached.get("n_atoms"),
        "relaxed_pdb": cached.get("relaxed_pdb"),
        "summary": cached.get("summary", {}),
    }


@router.get("/blade/jobs/{job_id}/trajectory")
async def get_blade_trajectory(job_id: str) -> dict:
    """The RELAXATION trajectory for the playback scrubber.

    ``{keys:[[helix,bp,dir,copy],…], frames:[[6 floats/key],…], n_frames}`` — the same wire
    shape as oxDNA's and SNUPI's ``/trajectory``, so the frontend scrubber/player
    (``framesToUpdates``) is reused unchanged.  Built by
    ``blade_runner._build_trajectory``, which routes the all-atom DCD through NAMD's
    ``md_composite_trajectory`` rather than inventing a BLADE-specific format."""
    from backend.core.blade_runner import load_trajectory

    job = _load_job(job_id)
    cached = load_trajectory(job.job_dir(_workspace()))
    if not cached or not cached.get("n_frames"):
        return {
            "job_id": job.job_id,
            "ready": False,
            "keys": [],
            "frames": [],
            "n_frames": 0,
        }
    return {"job_id": job.job_id, "ready": True, **cached}


@router.get("/blade/available")
async def get_blade_available() -> dict:
    """Whether a BLADE relax can actually run here, and why not if it can't.

    Unlike CanDo/SNUPI (in-process, always available) BLADE needs three external things: an
    interpreter that can import openmm+parmed, and psfgen for the topology build.  The probe
    spawns that interpreter, so it takes a second or two — the panel calls it once on tab
    open, not per poll."""
    from backend.core.blade_runner import blade_available, find_blade_python

    ok, reason = await run_in_threadpool(blade_available)
    return {
        "available": ok,
        "solver": "openmm-obc2",
        "reason": reason,
        "python": find_blade_python(),
    }
