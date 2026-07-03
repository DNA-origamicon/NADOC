"""
mrDNA relaxation job routes — create, inspect, control, and display.

Sibling of ``routes_oxdna.py`` (oxDNA jobs), simplified: a mrDNA job runs a
SINGLE coarse ARBD relaxation stage (mrDNA's coarse stage starts from an energy
minimisation, so it IS the relaxation — one job / one stage / one button).  All
routes prefixed with /api.  Mounted in ``backend/api/main.py``.

Route summary
─────────────
POST   /mrdna/jobs                 create + prepare a coarse relaxation job
GET    /mrdna/jobs                  list all jobs
GET    /mrdna/jobs/{id}             single job status
GET    /mrdna/jobs/{id}/progress    overall progress fraction + ETA
POST   /mrdna/jobs/{id}/start       start or resume a queued/stopped/failed job
POST   /mrdna/jobs/{id}/stop        stop a running job (kills the ARBD child)
DELETE /mrdna/jobs/{id}             delete job + generated files
GET    /mrdna/jobs/{id}/display     relaxed positions → applyFemPositions list
GET    /mrdna/jobs/{id}/beads       CG bead cloud (nm) for the bead representation
GET    /mrdna/jobs/{id}/error-log   failure log for the UI popup
GET    /mrdna/available             probe for a usable mrDNA + ARBD install

Display note: a mrDNA coarse relaxation yields a single relaxed configuration
(not a user-scrubbable trajectory), so /display and /beads return their cached
JSON directly.  mrDNA output is Physical-layer only; it never mutates topology.
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
from backend.core.mrdna_job import MrdnaJob, MrdnaStatus, new_mrdna_job
from backend.core.mrdna_runner import (
    is_running,
    job_progress,
    load_beads_with_edges,
    load_curvature,
    load_display,
    mrdna_available,
    prepare_mrdna_job,
    reconcile_mrdna_status,
    start_job,
    stop_job,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mrdna"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _workspace() -> Path:
    return _WORKSPACE_DIR


def _load_job(job_id: str) -> MrdnaJob:
    try:
        job = MrdnaJob.load(job_id, _workspace())
    except FileNotFoundError:
        raise HTTPException(404, f"mrDNA job {job_id!r} not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Failed to load job {job_id}: {exc}")
    return reconcile_mrdna_status(job, _workspace())


def _current_fingerprint() -> "str | None":
    from backend.core.oxdna_staleness import oxdna_design_fingerprint
    design = design_state.get_design()
    if design is None:
        return None
    try:
        return oxdna_design_fingerprint(design)
    except Exception:  # noqa: BLE001
        return None


def _is_out_of_date(job: MrdnaJob, current_fp: "str | None") -> bool:
    from backend.core.oxdna_staleness import job_out_of_date
    return job_out_of_date(job.design_fingerprint, current_fp)


# ── Request models ────────────────────────────────────────────────────────────

class CreateMrdnaJobRequest(BaseModel):
    coarse_steps:  int = Field(100_000, ge=1_000, le=50_000_000,
                               description="Coarse ARBD relaxation steps (mrDNA default 1e5)")
    fine_steps:    int = Field(0, ge=0, le=50_000_000,
                               description="Fine-stage steps (2 bp/bead + twist). >0 develops "
                                           "loop/skip CURVATURE; 0 = coarse-only (fast, no bend).")
    output_period: int = Field(10_000, ge=100,
                               description="Steps between DCD frames")
    device:        str = Field("0", description="CUDA device index")
    autostart:     bool = Field(True)
    design_source_path: Optional[str] = Field(None, description="Workspace path of the active design")


# ── Create / list / status ────────────────────────────────────────────────────

@router.post("/mrdna/jobs")
async def create_mrdna_job(body: CreateMrdnaJobRequest) -> dict:
    """Prepare a new coarse mrDNA relaxation job from the active design."""
    avail = mrdna_available()
    if not avail["available"]:
        missing = "mrDNA" if not avail["mrdna"] else "ARBD"
        raise HTTPException(
            400,
            f"{missing} is not installed. Open Help ▸ MD Engines to install mrDNA "
            "(one-click) and ARBD (needs a CUDA GPU) before running a mrDNA relaxation.",
        )

    design = design_state.get_or_404()
    if not design.helices:
        raise HTTPException(400, "Design has no helices to relax.")

    name = None
    if body.design_source_path:
        name = Path(body.design_source_path).stem or None
    name = (name or design.metadata.name or "design").replace(" ", "_")

    from backend.core.oxdna_staleness import (
        effective_feature_log_position,
        oxdna_design_fingerprint,
    )
    from backend.physics.oxdna_interface import _strand_nucleotide_order

    job = new_mrdna_job(
        design_name        = name,
        coarse_steps       = body.coarse_steps,
        fine_steps         = body.fine_steps,
        output_period      = body.output_period,
        n_nucleotides      = len(_strand_nucleotide_order(design)),
        device             = body.device,
        design_source_path = body.design_source_path,
        design_fingerprint = oxdna_design_fingerprint(design),
        feature_log_position = effective_feature_log_position(design),
    )
    job.status = MrdnaStatus.preparing
    job.save(_workspace())
    logger.info("create_mrdna_job: job_id=%s design=%s steps=%d",
                job.job_id, name, body.coarse_steps)

    try:
        await run_in_threadpool(prepare_mrdna_job, design, job, _workspace())
    except Exception as exc:  # noqa: BLE001
        logger.error("create_mrdna_job: prepare FAILED for %s: %s", job.job_id, exc, exc_info=True)
        job.status = MrdnaStatus.failed
        job.error = f"Preparation failed: {exc}"
        job.save(_workspace())
        return job.to_dict()

    job.status = MrdnaStatus.queued
    job.save(_workspace())
    if body.autostart:
        start_job(job, _workspace())
    return job.to_dict()


@router.get("/mrdna/jobs")
async def list_mrdna_jobs() -> list[dict]:
    from backend.core.design_disk_usage import dir_size_bytes_cached
    ws = _workspace()
    jobs = [reconcile_mrdna_status(j, ws) for j in MrdnaJob.list_jobs(ws)]
    current_fp = _current_fingerprint()
    out: list[dict] = []
    for j in jobs:
        d = j.to_dict()
        d["out_of_date"] = _is_out_of_date(j, current_fp)
        d["size_bytes"] = dir_size_bytes_cached(j.job_dir(ws))
        out.append(d)
    return out


@router.get("/mrdna/jobs/{job_id}")
async def get_mrdna_job(job_id: str) -> dict:
    job = _load_job(job_id)
    d = job.to_dict()
    d["out_of_date"] = _is_out_of_date(job, _current_fingerprint())
    return d


@router.get("/mrdna/jobs/{job_id}/progress")
async def get_mrdna_progress(job_id: str) -> dict:
    job = _load_job(job_id)
    return job_progress(job, _workspace())


@router.get("/mrdna/jobs/{job_id}/error-log")
async def get_mrdna_error_log(job_id: str) -> dict:
    """Failure detail for the UI's 'Error log' popup."""
    job = _load_job(job_id)
    return {
        "job_id": job_id,
        "status": job.status.value,
        "error": job.error or "",
        "log": job.error or "(no error recorded)",
    }


# ── Control ───────────────────────────────────────────────────────────────────

@router.post("/mrdna/jobs/{job_id}/start")
async def start_mrdna_job(job_id: str) -> dict:
    job = _load_job(job_id)
    if is_running(job_id):
        return {"ok": True, "message": "Job already running"}
    if job.status in (MrdnaStatus.running, MrdnaStatus.completed):
        raise HTTPException(400, f"Job is {job.status.value} — cannot start")
    if not mrdna_available()["available"]:
        raise HTTPException(400, "mrDNA or ARBD is not installed.")
    # Reset the single coarse stage and relaunch from the persisted snapshot.
    if job.stages:
        job.stages[0].status = "pending"
        job.stages[0].started_at = None
    job.status = MrdnaStatus.running
    job.error = None
    job.save(_workspace())
    start_job(job, _workspace())
    return {"ok": True, "job_id": job_id, "status": "running"}


@router.post("/mrdna/jobs/{job_id}/stop")
async def stop_mrdna_job(job_id: str) -> dict:
    job = _load_job(job_id)
    stopped = stop_job(job_id, _workspace())
    if not stopped:
        if job.status == MrdnaStatus.running:
            job.status = MrdnaStatus.stopped
            job.save(_workspace())
        return {"ok": True, "message": "Job was not actively running"}
    return {"ok": True, "job_id": job_id, "status": "stopping"}


@router.delete("/mrdna/jobs/{job_id}")
async def delete_mrdna_job(job_id: str) -> dict:
    ws = _workspace()
    job = _load_job(job_id)
    if is_running(job_id) or job.status == MrdnaStatus.running:
        raise HTTPException(400, "Stop the mrDNA job before deleting it")
    from backend.core.job_archive import purge_index_entry
    jd = job.job_dir(ws)
    if jd.exists():
        shutil.rmtree(jd)
    purge_index_entry(ws, "mrdna_jobs", job.job_id)
    return {"ok": True, "job_id": job_id}


# ── Display ───────────────────────────────────────────────────────────────────

@router.get("/mrdna/jobs/{job_id}/display")
async def get_mrdna_display(job_id: str) -> dict:
    """Relaxed per-nucleotide positions as an applyFemPositions update list.

    Returns the cached ``display.json`` (per-helix coarse-spline reconstruction).
    """
    job = _load_job(job_id)
    cached = load_display(job.job_dir(_workspace()))
    if not cached or not cached.get("positions"):
        return {"job_id": job.job_id, "ready": False, "positions": []}
    positions = cached["positions"]
    return {
        "job_id": job.job_id,
        "ready": True,
        "status": job.status.value,
        "n_positions": len(positions),
        "positions": positions,
    }


@router.get("/mrdna/jobs/{job_id}/beads")
async def get_mrdna_beads(job_id: str) -> dict:
    """The coarse CG bead cloud (nm, aligned to the design pose) for the bead
    representation toggle."""
    job = _load_job(job_id)
    cached = load_beads_with_edges(job.job_dir(_workspace()))
    if not cached or not cached.get("beads"):
        return {"job_id": job.job_id, "ready": False, "beads": [], "edges": []}
    beads = cached["beads"]
    edges = cached.get("edges", [])
    return {
        "job_id": job.job_id,
        "ready": True,
        "n_beads": len(beads),
        "beads": beads,
        "edges": edges,
    }


@router.get("/mrdna/jobs/{job_id}/curvature")
async def get_mrdna_curvature(job_id: str) -> dict:
    """Designed (analytic Dietz) vs simulated (mrDNA) curvature for the panel readout.

    NOTE: curvature is a twist-coupled effect that only the FINE stage develops — a
    coarse-only job reads ~straight regardless of the loop/skip marks.  ``fine`` in
    the response flags whether this job ran the fine stage.
    """
    job = _load_job(job_id)
    report = load_curvature(job.job_dir(_workspace()))
    if report is None:
        # No snapshot to compute from (or job not prepared) — analytic-only fallback.
        from backend.core.mrdna_curvature import curvature_report
        design = design_state.get_design()
        report = curvature_report(design, None) if design is not None else {
            "analytic": None, "measured": None, "ratio": None}
    return {
        "job_id": job.job_id,
        "ready": job.status == MrdnaStatus.completed,
        "fine": job.fine_steps > 0,
        **report,
    }


@router.get("/mrdna/curvature/analytic")
async def get_mrdna_analytic_curvature() -> dict:
    """Analytic Dietz curvature of the ACTIVE design's loop/skip pattern — available
    with no run (instant), so the panel can show the designed curvature up front."""
    from backend.core.mrdna_curvature import analytic_curvature
    design = design_state.get_design()
    if design is None:
        return {"analytic": None}
    return {"analytic": analytic_curvature(design)}


@router.get("/mrdna/available")
async def get_mrdna_available() -> dict:
    """Probe for a usable mrDNA + ARBD install (mirror /oxdna/available)."""
    return mrdna_available()
