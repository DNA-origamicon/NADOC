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


def _required_manifest(job: MrdnaJob):
    """Load the identity contract or report an intentional legacy-job error."""
    from backend.core.mrdna_manifest import MrdnaNucleotideManifest

    try:
        return MrdnaNucleotideManifest.load_required(job.job_dir(_workspace()))
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _confidence_summary(manifest) -> dict:
    direct = sum(r.simulation_mode == "direct" for r in manifest.records)
    interpolated = len(manifest.records) - direct
    return {
        "direct": direct,
        "interpolated": interpolated,
        "lower_confidence": interpolated > 0,
    }


# ── Request models ────────────────────────────────────────────────────────────


class CreateMrdnaJobRequest(BaseModel):
    coarse_steps: int = Field(
        100_000,
        ge=1_000,
        le=50_000_000,
        description="Coarse ARBD relaxation steps (mrDNA default 1e5)",
    )
    fine_steps: int = Field(
        0,
        ge=0,
        le=50_000_000,
        description="Fine-stage steps (2 bp/bead + twist). >0 develops "
        "loop/skip CURVATURE; 0 = coarse-only (fast, no bend).",
    )
    output_period: int = Field(10_000, ge=100, description="Steps between DCD frames")
    device: str = Field("0", description="CUDA device index")
    autostart: bool = Field(True)
    design_source_path: Optional[str] = Field(
        None, description="Workspace path of the active design"
    )
    anchors: Optional[list] = Field(
        None,
        description="Anchor scopes (shared oxDNA/CanDo/NAMD picker format: overhang / "
        "cluster / domain / strand / base) held immobile via ARBD harmonic "
        "RESTRAINTs on the covering CG beads. A JOB-REQUEST annotation, never "
        "a Design edit; a selection resolving to nothing leaves the run "
        "unanchored (needed under a uniform field to stop COM drift).",
    )
    field: Optional[dict] = Field(
        None,
        description="Uniform E-field descriptor (shared oxDNA/NAMD/CanDo form: "
        '{"field_pN": <force per NUCLEOTIDE, pN>, "dir": [x,y,z]}) applied '
        "as a constant per-bead force via ARBD force grids, scaled by each "
        "bead's nucleotide content. A JOB-REQUEST annotation, never a Design "
        "edit. Requires >=1 anchor (or an opposing surface) to hold against "
        "COM drift.",
    )
    surface: Optional[dict] = Field(
        None,
        description="Hard-surface (repulsion-plane) descriptor (shared oxDNA/LAMMPS form: "
        '{"dir": [x,y,z], "offset_nm": d, "stiff": s}) realised as a '
        "one-sided harmonic wall via an ARBD grid potential. A JOB-REQUEST "
        "annotation, never a Design edit. A field pressing straight into the "
        "surface is held by its reaction, so it needs no strand anchor.",
    )


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

    design = design_state.get_or_404().without_reference_geometry()
    if not design.helices:
        raise HTTPException(400, "Design has no helices to relax.")

    if body.surface:
        from backend.core.mrdna_surface import parse_surface

        try:
            parsed_surface = parse_surface(body.surface)
        except (ValueError, TypeError):
            parsed_surface = None
        if parsed_surface is None:
            raise HTTPException(
                400,
                'Malformed surface: expected {"dir": [x,y,z], "offset_nm": d, '
                '"stiff": <non-zero>} with a non-zero direction.',
            )

    if body.field:
        from backend.core.mrdna_field import parse_field

        try:
            parsed_field = parse_field(body.field)
        except (ValueError, TypeError):
            parsed_field = None
        if parsed_field is None:
            raise HTTPException(
                400,
                'Malformed E-field: expected {"field_pN": <non-zero pN>, '
                '"dir": [x,y,z]} with a non-zero direction.',
            )
        # An unanchored uniform field streams the whole structure down-field (COM
        # drift); anchors are recommended but no longer required — the UI warns.

    name = None
    if body.design_source_path:
        name = Path(body.design_source_path).stem or None
    name = (name or design.metadata.name or "design").replace(" ", "_")

    from backend.core.oxdna_staleness import (
        effective_feature_log_position,
        oxdna_design_fingerprint,
    )
    from backend.physics.oxdna_interface import _strand_nucleotide_order
    from backend.core.project_revisions import record_simulation_revision

    job = new_mrdna_job(
        design_name=name,
        coarse_steps=body.coarse_steps,
        fine_steps=body.fine_steps,
        output_period=body.output_period,
        n_nucleotides=len(_strand_nucleotide_order(design)),
        device=body.device,
        anchors=body.anchors,
        e_field=body.field,
        surface=body.surface,
        design_source_path=body.design_source_path,
        design_fingerprint=oxdna_design_fingerprint(design),
        feature_log_position=effective_feature_log_position(design),
    )
    provenance = record_simulation_revision(_workspace(), design, "mrdna", job.job_id)
    job.project_id = provenance.project_id
    job.design_revision_id = provenance.revision_id
    job.status = MrdnaStatus.preparing
    job.save(_workspace())
    logger.info(
        "create_mrdna_job: job_id=%s design=%s steps=%d",
        job.job_id,
        name,
        body.coarse_steps,
    )

    try:
        await run_in_threadpool(prepare_mrdna_job, design, job, _workspace())
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "create_mrdna_job: prepare FAILED for %s: %s",
            job.job_id,
            exc,
            exc_info=True,
        )
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
        if d.get("status") == "running":
            p = job_progress(j, ws)
            d["progress_fraction"] = round(float(p.get("overall") or 0.0), 4)
            d["eta_seconds"] = p.get("eta_seconds")
            d["stage_name"] = p.get("stage_name")
            d["stage_fraction"] = p.get("stage_fraction")
            d["phase"] = p.get("stage_name")
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


@router.get("/mrdna/jobs/{job_id}/snapshot-geometry")
async def get_mrdna_snapshot_geometry(job_id: str) -> dict:
    """Full geometry of the job's own design snapshot for visualization overlays."""
    from backend.core.deformation import (
        _apply_ovhg_rotations_to_axes,
        deformed_helix_axes,
    )
    from backend.core.design_geometry import _geometry_for_helices
    from backend.core.mrdna_runner import _load_snapshot_design

    job = _load_job(job_id)
    _required_manifest(job)
    design = _load_snapshot_design(job.job_dir(_workspace()))
    if design is None or not design.helices:
        return {"job_id": job.job_id, "ready": False, "nucleotides": [], "helix_axes": []}

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


@router.get("/mrdna/jobs/{job_id}/display")
async def get_mrdna_display(job_id: str) -> dict:
    """Relaxed per-nucleotide positions as an applyFemPositions update list.

    Returns the cached ``display.json`` (per-helix coarse-spline reconstruction).
    """
    job = _load_job(job_id)
    manifest = _required_manifest(job)
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
        "confidence": _confidence_summary(manifest),
    }


@router.get("/mrdna/jobs/{job_id}/beads")
async def get_mrdna_beads(job_id: str) -> dict:
    """The coarse CG bead cloud (nm, aligned to the design pose) for the bead
    representation toggle."""
    job = _load_job(job_id)
    manifest = _required_manifest(job)
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
        "confidence": _confidence_summary(manifest),
    }


@router.get("/mrdna/jobs/{job_id}/rmsf")
async def get_mrdna_rmsf(job_id: str) -> dict:
    """Trajectory RMSF and mean reconstructed positions for the flexibility map."""
    from backend.core.mrdna_runner import _load_snapshot_design, mrdna_trajectory_rmsf

    job = _load_job(job_id)
    manifest = _required_manifest(job)
    jd = job.job_dir(_workspace())
    design = _load_snapshot_design(jd)
    if design is None:
        raise HTTPException(500, f"mrDNA job {job_id!r} has no design snapshot")
    result = await run_in_threadpool(mrdna_trajectory_rmsf, design, jd)
    if not result or not result.get("positions"):
        return {"job_id": job.job_id, "ready": False, "positions": []}
    positions = [
        {**p, "rmsf": p.get("rmsf_nm")}
        for p in result["positions"]
        if p.get("rmsf_nm") is not None
    ]
    vals = [p["rmsf"] for p in positions]
    return {
        "job_id": job.job_id,
        "ready": bool(positions),
        "positions": positions,
        "n_frames": result.get("n_frames"),
        "min_rmsf": min(vals) if vals else None,
        "max_rmsf": max(vals) if vals else None,
        "mean_rmsf": sum(vals) / len(vals) if vals else None,
        "confidence": _confidence_summary(manifest),
    }


@router.get("/mrdna/jobs/{job_id}/deviation")
async def get_mrdna_deviation(job_id: str) -> dict:
    """Relaxed mrDNA shape deviation from the job snapshot's intended geometry."""
    from backend.core.design_geometry import _geometry_for_helices
    from backend.core.mrdna_runner import _load_snapshot_design
    from backend.core.shape_metrics import deviation_profile

    job = _load_job(job_id)
    manifest = _required_manifest(job)
    jd = job.job_dir(_workspace())
    cached = load_display(jd)
    if not cached or not cached.get("positions"):
        return {"job_id": job.job_id, "ready": False, "positions": []}
    design = _load_snapshot_design(jd)
    if design is None:
        raise HTTPException(500, f"mrDNA job {job_id!r} has no design snapshot")
    reference = await run_in_threadpool(
        _geometry_for_helices, design, None, junction_balance=True
    )
    result = await run_in_threadpool(
        deviation_profile, cached["positions"], reference, align=True
    )
    return {
        "job_id": job.job_id,
        "ready": True,
        **result,
        "confidence": _confidence_summary(manifest),
    }


@router.get("/mrdna/jobs/{job_id}/strain")
async def get_mrdna_strain(job_id: str) -> dict:
    """Identity-preserving geometric backbone strain for the relaxed frame."""
    from backend.core.design_geometry import _geometry_for_helices
    from backend.core.mrdna_decoder import mrdna_backbone_strain_profile
    from backend.core.mrdna_runner import _load_snapshot_design

    job = _load_job(job_id)
    manifest = _required_manifest(job)
    jd = job.job_dir(_workspace())
    cached = load_display(jd)
    if not cached or not cached.get("positions"):
        return {"job_id": job.job_id, "ready": False, "positions": []}
    design = _load_snapshot_design(jd)
    if design is None:
        raise HTTPException(500, f"mrDNA job {job_id!r} has no design snapshot")
    reference = await run_in_threadpool(
        _geometry_for_helices, design, None, junction_balance=True
    )
    result = await run_in_threadpool(
        mrdna_backbone_strain_profile, manifest, cached["positions"], reference
    )
    return {
        "job_id": job.job_id,
        "ready": bool(result["positions"]),
        **result,
        "confidence": _confidence_summary(manifest),
    }


@router.get("/mrdna/jobs/{job_id}/curvature")
async def get_mrdna_curvature(job_id: str) -> dict:
    """Designed (analytic Dietz) vs simulated (mrDNA) curvature for the panel readout.

    NOTE: curvature is a twist-coupled effect that only the FINE stage develops — a
    coarse-only job reads ~straight regardless of the loop/skip marks.  ``fine`` in
    the response flags whether this job ran the fine stage.
    """
    job = _load_job(job_id)
    _required_manifest(job)
    report = load_curvature(job.job_dir(_workspace()))
    if report is None:
        # No snapshot to compute from (or job not prepared) — analytic-only fallback.
        from backend.core.mrdna_curvature import curvature_report

        design = design_state.get_design()
        report = (
            curvature_report(design, None)
            if design is not None
            else {"analytic": None, "measured": None, "ratio": None}
        )
    return {
        "job_id": job.job_id,
        "ready": job.status == MrdnaStatus.completed,
        "fine": job.fine_steps > 0,
        **report,
    }


@router.get("/mrdna/jobs/{job_id}/shape-source")
async def get_mrdna_shape_source(job_id: str) -> dict:
    """The mrDNA source bundle for the cross-engine comparison card (S5/M5).

    Turns the job's relaxed display frame + a per-nucleotide RMSF from the CG trajectory
    ensemble into the shared ``{engine, descriptors, rmsf, shape_frame, field}`` bundle
    ``build_comparison_report`` consumes — mrDNA's ABSOLUTE twist/bend on the rigid dsDNA
    core (a third live column, cross-validated against oxDNA's relaxed shape) + its
    trajectory-variance RMSF.  Uses the job's OWN design snapshot for the core mask + the
    per-frame reconstruction, so the descriptors match what mrDNA relaxed, not live editor
    state.  Physical-layer only (Three-Layer Law); field emission is deferred
    (``field:None`` — see :mod:`backend.core.mrdna_shape_source`)."""
    from backend.api.skip_twist_tuning import core_reference_geometry
    from backend.core.mrdna_runner import _load_snapshot_design, mrdna_trajectory_rmsf
    from backend.core.mrdna_shape_source import build_mrdna_shape_source

    job = _load_job(job_id)
    manifest = _required_manifest(job)
    jd = job.job_dir(_workspace())
    cached = load_display(jd)
    if not cached or not cached.get("positions"):
        return {"job_id": job.job_id, "ready": False}
    design = _load_snapshot_design(jd)
    if design is None:
        raise HTTPException(
            500, f"mrDNA job {job_id!r} has no design snapshot to compare against"
        )

    rmsf = await run_in_threadpool(mrdna_trajectory_rmsf, design, jd)
    reference = await run_in_threadpool(core_reference_geometry, design)
    bundle = await run_in_threadpool(
        build_mrdna_shape_source,
        cached["positions"],
        reference,
        rmsf=(rmsf["positions"] if rmsf else None),
    )
    return {
        "job_id": job.job_id,
        "ready": bundle["descriptors"] is not None,
        "n_frames": (rmsf["n_frames"] if rmsf else None),
        "confidence": _confidence_summary(manifest),
        **bundle,
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
