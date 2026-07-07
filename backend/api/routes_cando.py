"""
CanDo FEM job routes — create, inspect, control, and display.

Sibling of ``routes_mrdna.py`` (mrDNA jobs), simplified: a CanDo job runs the
native FEM shape predictor in-process (no external simulator, no GPU), so there
is no availability probe and no subprocess to kill.  The two "engines" are the
solver modes — Coarse = linear preview, Fine = nonlinear corotational solve.
All routes prefixed with /api.  Mounted in ``backend/api/main.py``.

Route summary
─────────────
POST   /cando/jobs                 create + run a FEM shape-prediction job
GET    /cando/jobs                  list all jobs
GET    /cando/jobs/{id}             single job status
GET    /cando/jobs/{id}/progress    overall progress fraction + ETA
POST   /cando/jobs/{id}/start       start or resume a queued/stopped/failed job
POST   /cando/jobs/{id}/stop        stop a running job (best-effort cancel)
DELETE /cando/jobs/{id}             delete job + generated files
GET    /cando/jobs/{id}/snapshot-geometry  full geometry of the job's OWN design snapshot
GET    /cando/jobs/{id}/display     predicted positions → applyFemPositions list
GET    /cando/jobs/{id}/rmsf        per-bp RMSF (nm) for the flex map (Item 3)
GET    /cando/jobs/{id}/deviation   per-bp deviation from the intended shape + RMSD (Item 3)
GET    /cando/jobs/{id}/cylinders   CanDo-style jointed-cylinder geometry (tubes + joints)
GET    /cando/jobs/{id}/shape-source shared cross-engine descriptors + RMSF bundle (S5/C5)
GET    /cando/jobs/{id}/error-log   failure log for the UI popup
GET    /cando/available             always {available:true} (in-process solver)

Display note: FEM output is Physical-layer only; it never mutates topology.
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
from backend.core.cando_job import CandoJob, CandoStatus, new_cando_job
from backend.core.cando_runner import (
    is_running,
    job_progress,
    load_display,
    load_rmsf,
    prepare_cando_job,
    reconcile_cando_status,
    start_job,
    stop_job,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cando"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _workspace() -> Path:
    return _WORKSPACE_DIR


def _load_job(job_id: str) -> CandoJob:
    try:
        job = CandoJob.load(job_id, _workspace())
    except FileNotFoundError:
        raise HTTPException(404, f"CanDo job {job_id!r} not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Failed to load job {job_id}: {exc}")
    return reconcile_cando_status(job, _workspace())


def _current_fingerprint() -> "str | None":
    from backend.core.oxdna_staleness import oxdna_design_fingerprint
    design = design_state.get_design()
    if design is None:
        return None
    try:
        return oxdna_design_fingerprint(design)
    except Exception:  # noqa: BLE001
        return None


def _is_out_of_date(job: CandoJob, current_fp: "str | None") -> bool:
    from backend.core.oxdna_staleness import job_out_of_date
    return job_out_of_date(job.design_fingerprint, current_fp)


# ── Request models ────────────────────────────────────────────────────────────

class CreateCandoJobRequest(BaseModel):
    kind:       str = Field("predict",
                            description="'predict' (plain FEM shape prediction) or 'autorefine' "
                                        "(tune the loop/skip program, auto-apply it as a reversible "
                                        "feature-log entry, then cache the FEM analysis of the "
                                        "refined design so all display modes work on the job).")
    nonlinear:  bool = Field(True,
                             description="Fine (geometrically-nonlinear corotational, "
                                         "~0.95·CanDo) vs Coarse (linear preview, ~0.92).  For an "
                                         "autorefine job this is also the per-trial oracle mode.")
    n_steps:    int = Field(20, ge=1, le=200,
                            description="Corotational load-step count (nonlinear only)")
    with_rmsf:  bool = Field(True, description="Also compute the free-free NMA per-bp RMSF")
    # Job-request annotations (C1/C2): anchors held fixed (Dirichlet BC) + a uniform E-field body
    # load, both threaded into predict_shape(...).  Never a topology edit (Three-Layer Law).
    anchors:    Optional[list] = Field(None, description="Shared oxDNA anchor-scope descriptors "
                                       "(overhang/cluster/domain/strand/base) held fixed during the solve")
    field:      Optional[dict] = Field(None, description="Uniform E-field {field_pN, dir} — the same "
                                       "per-nucleotide force oxDNA applies; needs ≥1 anchor (COM drift)")
    autostart:  bool = Field(True)
    design_source_path: Optional[str] = Field(None, description="Workspace path of the active design")


# ── Create / list / status ────────────────────────────────────────────────────

@router.post("/cando/jobs")
async def create_cando_job(body: CreateCandoJobRequest) -> dict:
    """Prepare + run a new CanDo FEM shape-prediction job from the active design."""
    design = design_state.get_or_404()
    if not design.helices:
        raise HTTPException(400, "Design has no helices to predict a shape for.")

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

    kind = body.kind if body.kind in ("predict", "autorefine") else "predict"
    job = new_cando_job(
        design_name        = name,
        kind               = kind,
        nonlinear          = body.nonlinear,
        n_steps            = body.n_steps,
        with_rmsf          = body.with_rmsf,
        # Autorefine is a free-free design-optimization loop → don't drive it with anchors/field
        # (they'd change the twist/bend objective); they apply only to a plain predict job.
        anchors            = body.anchors if kind == "predict" else None,
        field              = body.field if kind == "predict" else None,
        n_nucleotides      = len(_strand_nucleotide_order(design)),
        design_source_path = body.design_source_path,
        design_fingerprint = oxdna_design_fingerprint(design),
        feature_log_position = effective_feature_log_position(design),
        # Autorefine auto-applies from its worker thread → bind the job to the current document so
        # the feature-log entry lands on the right design in a multi-doc session.
        doc_id             = doc_context.get_current_doc(),
    )
    job.status = CandoStatus.preparing
    job.save(_workspace())
    logger.info("create_cando_job: job_id=%s design=%s nonlinear=%s",
                job.job_id, name, body.nonlinear)

    try:
        await run_in_threadpool(prepare_cando_job, design, job, _workspace())
    except Exception as exc:  # noqa: BLE001
        logger.error("create_cando_job: prepare FAILED for %s: %s", job.job_id, exc, exc_info=True)
        job.status = CandoStatus.failed
        job.error = f"Preparation failed: {exc}"
        job.save(_workspace())
        return job.to_dict()

    job.status = CandoStatus.queued
    job.save(_workspace())
    if body.autostart:
        start_job(job, _workspace())
    return job.to_dict()


@router.get("/cando/jobs")
async def list_cando_jobs() -> list[dict]:
    from backend.core.design_disk_usage import dir_size_bytes_cached
    ws = _workspace()
    jobs = [reconcile_cando_status(j, ws) for j in CandoJob.list_jobs(ws)]
    current_fp = _current_fingerprint()
    out: list[dict] = []
    for j in jobs:
        d = j.to_dict()
        d["out_of_date"] = _is_out_of_date(j, current_fp)
        d["size_bytes"] = dir_size_bytes_cached(j.job_dir(ws))
        out.append(d)
    return out


@router.get("/cando/jobs/{job_id}")
async def get_cando_job(job_id: str) -> dict:
    job = _load_job(job_id)
    d = job.to_dict()
    d["out_of_date"] = _is_out_of_date(job, _current_fingerprint())
    return d


@router.get("/cando/jobs/{job_id}/progress")
async def get_cando_progress(job_id: str) -> dict:
    job = _load_job(job_id)
    return job_progress(job, _workspace())


@router.get("/cando/jobs/{job_id}/error-log")
async def get_cando_error_log(job_id: str) -> dict:
    """Failure detail for the UI's 'Error log' popup."""
    job = _load_job(job_id)
    return {
        "job_id": job_id,
        "status": job.status.value,
        "error": job.error or "",
        "log": job.error or "(no error recorded)",
    }


# ── Control ───────────────────────────────────────────────────────────────────

@router.post("/cando/jobs/{job_id}/start")
async def start_cando_job(job_id: str) -> dict:
    job = _load_job(job_id)
    if is_running(job_id):
        return {"ok": True, "message": "Job already running"}
    if job.status in (CandoStatus.running, CandoStatus.completed):
        raise HTTPException(400, f"Job is {job.status.value} — cannot start")
    if job.stages:
        job.stages[0].status = "pending"
        job.stages[0].started_at = None
    job.status = CandoStatus.running
    job.error = None
    job.save(_workspace())
    start_job(job, _workspace())
    return {"ok": True, "job_id": job_id, "status": "running"}


@router.post("/cando/jobs/{job_id}/stop")
async def stop_cando_job(job_id: str) -> dict:
    job = _load_job(job_id)
    stopped = stop_job(job_id, _workspace())
    if not stopped:
        if job.status == CandoStatus.running:
            job.status = CandoStatus.stopped
            job.save(_workspace())
        return {"ok": True, "message": "Job was not actively running"}
    return {"ok": True, "job_id": job_id, "status": "stopping"}


@router.delete("/cando/jobs/{job_id}")
async def delete_cando_job(job_id: str) -> dict:
    ws = _workspace()
    job = _load_job(job_id)
    if is_running(job_id) or job.status == CandoStatus.running:
        raise HTTPException(400, "Stop the CanDo job before deleting it")
    from backend.core.job_archive import purge_index_entry
    jd = job.job_dir(ws)
    if jd.exists():
        shutil.rmtree(jd)
    purge_index_entry(ws, "cando_jobs", job.job_id)
    return {"ok": True, "job_id": job_id}


# ── Display ───────────────────────────────────────────────────────────────────

@router.get("/cando/jobs/{job_id}/snapshot-geometry")
async def get_cando_snapshot_geometry(job_id: str) -> dict:
    """The full geometry of the job's OWN design snapshot — the topology the design
    had when the analysis was run, not live editor state.  The CanDo display modes
    render THIS (hiding the live model) and then overlay the FEM-predicted shape on
    it, so a job whose snapshot differs from the current design (e.g. loops/skips
    added since) still shows the shape on the topology it was solved for.

    Same shape as ``GET /design/geometry`` plus the snapshot ``design`` object:
    ``{ready, design, nucleotides:[...], helix_axes:[{helix_id,start,end,...}]}``.
    """
    from backend.core.deformation import _apply_ovhg_rotations_to_axes, deformed_helix_axes
    from backend.core.design_geometry import _geometry_for_helices
    from backend.core.cando_runner import _load_snapshot_design

    job = _load_job(job_id)
    design = _load_snapshot_design(job.job_dir(_workspace()))
    if design is None or not design.helices:
        return {"job_id": job.job_id, "ready": False, "nucleotides": [], "helix_axes": []}

    def _compute() -> tuple[list, list]:
        nucleotides = _geometry_for_helices(design, None)
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


@router.get("/cando/jobs/{job_id}/display")
async def get_cando_display(job_id: str) -> dict:
    """Predicted per-nucleotide positions as an applyFemPositions update list."""
    job = _load_job(job_id)
    cached = load_display(job.job_dir(_workspace()))
    if not cached or not cached.get("positions"):
        return {"job_id": job.job_id, "ready": False, "positions": []}
    positions = cached["positions"]
    return {
        "job_id": job.job_id,
        "ready": True,
        "status": job.status.value,
        "solver": cached.get("solver"),
        "n_positions": len(positions),
        "positions": positions,
    }


@router.get("/cando/jobs/{job_id}/rmsf")
async def get_cando_rmsf(job_id: str) -> dict:
    """Per-bp RMSF (nm) for the flexibility map (Item 3).  One entry per FEM
    (duplex-core) node: ``{helix_id, bp_index, rmsf_nm}``."""
    job = _load_job(job_id)
    cached = load_rmsf(job.job_dir(_workspace()))
    if not cached or not cached.get("rmsf"):
        return {"job_id": job.job_id, "ready": False, "rmsf": []}
    rmsf = cached["rmsf"]
    vals = [r["rmsf_nm"] for r in rmsf]
    return {
        "job_id": job.job_id,
        "ready": True,
        "n": len(rmsf),
        "min_nm": min(vals) if vals else None,
        "max_nm": max(vals) if vals else None,
        "rmsf": rmsf,
    }


@router.get("/cando/jobs/{job_id}/deviation")
async def get_cando_deviation(job_id: str) -> dict:
    """Per-nucleotide deviation of the FEM-predicted shape from the design's intended
    (displayed) geometry + the global RMSD (Item 3 deviation map).  Uses the job's own
    design snapshot so the comparison matches what the FEM solved, not live editor state.

    ``{ready, positions:[{helix_id,bp_index,direction,backbone_position,deviation}],
        rmsd_nm, min_deviation, max_deviation, mean_deviation, n}``.
    """
    from backend.core.cando_deviation import compute_deviation
    from backend.core.cando_runner import _load_snapshot_design

    job = _load_job(job_id)
    jd = job.job_dir(_workspace())
    cached = load_display(jd)
    if not cached or not cached.get("positions"):
        return {"job_id": job.job_id, "ready": False, "positions": []}
    design = _load_snapshot_design(jd)
    if design is None:
        raise HTTPException(500, f"CanDo job {job_id!r} has no design snapshot to compare against")

    result = await run_in_threadpool(compute_deviation, design, cached["positions"])
    return {"job_id": job.job_id, "ready": True, **result}


@router.get("/cando/jobs/{job_id}/cylinders")
async def get_cando_cylinders(job_id: str) -> dict:
    """CanDo-style "jointed cylinder" geometry of the predicted shape: per-helix axis
    tubes + crossover joint connectors, in the aligned display frame.  Drives the
    "CanDo style output" display toggle.  Uses the job's cached display positions +
    its own design snapshot (crossovers), so it matches what the FEM solved.

    ``{ready, tube_radius_nm, joint_radius_nm, helices:[{helix_id,points}], joints, ...}``.
    """
    from backend.core.cando_cylinders import axis_from_backbones, compute_cylinders
    from backend.core.cando_runner import _load_snapshot_design

    job = _load_job(job_id)
    jd = job.job_dir(_workspace())
    cached = load_display(jd)
    if not cached or not cached.get("positions"):
        return {"job_id": job.job_id, "ready": False, "helices": [], "joints": []}
    design = _load_snapshot_design(jd)
    if design is None:
        raise HTTPException(500, f"CanDo job {job_id!r} has no design snapshot for cylinders")

    rmsf_cached = load_rmsf(jd)
    rmsf = rmsf_cached.get("rmsf") if rmsf_cached else None
    # Prefer the solver's cached helix-CENTRE axis nodes; older jobs cached without them
    # fall back to a (wobblier) backbone-midpoint reconstruction, ssDNA still excluded.
    axis_nodes = cached.get("axis") or axis_from_backbones(cached["positions"], rmsf)
    result = await run_in_threadpool(compute_cylinders, design, axis_nodes, rmsf)
    return {"job_id": job.job_id, "ready": True, **result}


@router.get("/cando/jobs/{job_id}/shape-source")
async def get_cando_shape_source(job_id: str) -> dict:
    """The CanDo source bundle for the cross-engine comparison card (S5/C5).

    Turns the job's cached FEM display frame + per-bp NMA RMSF into the shared
    ``{engine, descriptors, rmsf, shape_frame, field}`` bundle
    ``build_comparison_report`` consumes — CanDo's ABSOLUTE shape descriptors on the
    rigid dsDNA core + its free-free RMSF (the RMSF reference column).  Uses the job's OWN
    design snapshot for the core mask, so the descriptors match what the FEM solved, not
    live editor state.  Physical-layer only (Three-Layer Law); field emission is deferred
    (``field:None`` for now — see :mod:`backend.core.cando_shape_source`)."""
    from backend.api.skip_twist_tuning import core_reference_geometry
    from backend.core.cando_runner import _load_snapshot_design
    from backend.core.cando_shape_source import build_cando_shape_source

    job = _load_job(job_id)
    jd = job.job_dir(_workspace())
    cached = load_display(jd)
    if not cached or not cached.get("positions"):
        return {"job_id": job.job_id, "ready": False}
    design = _load_snapshot_design(jd)
    if design is None:
        raise HTTPException(500, f"CanDo job {job_id!r} has no design snapshot to compare against")

    rmsf_cached = load_rmsf(jd)
    rmsf = rmsf_cached.get("rmsf") if rmsf_cached else None
    reference = await run_in_threadpool(core_reference_geometry, design)
    bundle = await run_in_threadpool(
        build_cando_shape_source, cached["positions"], reference, rmsf=rmsf)
    ready = bundle["descriptors"] is not None
    return {"job_id": job.job_id, "ready": ready, **bundle}


@router.get("/cando/available")
async def get_cando_available() -> dict:
    """The CanDo FEM solver runs in-process (scipy) — always available.  Mirrors
    /mrdna/available so the panel's availability check has a uniform shape."""
    return {"available": True, "solver": "native-fem"}
