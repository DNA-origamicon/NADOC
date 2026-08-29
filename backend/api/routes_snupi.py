"""
SNUPI FEM job routes — create, inspect, control, and display.

Sibling of ``routes_cando.py``: a SNUPI job runs the SAME native FEM shape predictor
in-process, with the anisotropic SNUPI material law (``predict_shape(..., material="snupi")``)
instead of CanDo's isotropic rod.  No external simulator, no GPU, so there is no
availability probe and no subprocess to kill.  The two "engines" are the solver modes —
Coarse = linear preview, Fine = nonlinear corotational solve.  All routes prefixed with
/api.  Mounted in ``backend/api/main.py``.

The display processors (deviation, cylinders, shape-source) are material-agnostic — they
operate on the job's cached FEM display frame + its design snapshot — so this module
reuses ``cando_deviation`` / ``cando_cylinders`` / ``cando_shape_source`` directly rather
than re-implementing them.

Route summary
─────────────
POST   /snupi/jobs                 create + run a FEM shape-prediction job
GET    /snupi/jobs                  list all jobs
GET    /snupi/jobs/{id}             single job status
GET    /snupi/jobs/{id}/progress    overall progress fraction + ETA
POST   /snupi/jobs/{id}/start       start or resume a queued/stopped/failed job
POST   /snupi/jobs/{id}/stop        stop a running job (best-effort cancel)
DELETE /snupi/jobs/{id}             delete job + generated files
GET    /snupi/jobs/{id}/snapshot-geometry  full geometry of the job's OWN design snapshot
GET    /snupi/jobs/{id}/display     predicted positions → applyFemPositions list
GET    /snupi/jobs/{id}/display-bin compact static FEM frame
GET    /snupi/jobs/{id}/rmsf        per-bp RMSF (nm) for the flex map
GET    /snupi/jobs/{id}/deviation   per-bp deviation from the intended shape + RMSD
GET    /snupi/jobs/{id}/cylinders   CanDo-style jointed-cylinder geometry (tubes + joints)
GET    /snupi/jobs/{id}/shape-source shared cross-engine descriptors + RMSF bundle
GET    /snupi/jobs/{id}/error-log   failure log for the UI popup
GET    /snupi/available             always {available:true} (in-process solver)

Display note: FEM output is Physical-layer only; it never mutates topology.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.api import state as design_state
from backend.api.assembly import _WORKSPACE_DIR
from backend.core.snupi_job import SnupiJob, SnupiStatus, new_snupi_job
from backend.core.snupi_runner import (
    is_running,
    job_progress,
    load_display,
    load_display_bin,
    load_rmsf,
    prepare_snupi_job,
    reconcile_snupi_status,
    start_job,
    stop_job,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["snupi"])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _workspace() -> Path:
    return _WORKSPACE_DIR


def _load_job(job_id: str) -> SnupiJob:
    try:
        job = SnupiJob.load(job_id, _workspace())
    except FileNotFoundError:
        raise HTTPException(404, f"SNUPI job {job_id!r} not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Failed to load job {job_id}: {exc}")
    return reconcile_snupi_status(job, _workspace())


def _current_fingerprint() -> "str | None":
    from backend.core.oxdna_staleness import oxdna_design_fingerprint

    design = design_state.get_design()
    if design is None:
        return None
    try:
        return oxdna_design_fingerprint(design)
    except Exception:  # noqa: BLE001
        return None


def _is_out_of_date(job: SnupiJob, current_fp: "str | None") -> bool:
    from backend.core.oxdna_staleness import job_out_of_date

    return job_out_of_date(job.design_fingerprint, current_fp)


# ── Request models ────────────────────────────────────────────────────────────


class CreateSnupiJobRequest(BaseModel):
    nonlinear: bool = Field(
        True,
        description="Fine (geometrically-nonlinear corotational) vs Coarse "
        "(linear preview)",
    )
    n_steps: int = Field(
        20, ge=1, le=200, description="Corotational load-step count (nonlinear only)"
    )
    with_rmsf: bool = Field(
        True, description="Also compute the free-free NMA per-bp RMSF"
    )
    material: str = Field(
        "snupi",
        description="Intra-helix beam constitutive law: 'snupi' (anisotropic "
        "per-motif 6×6 + twist–stretch couplings + compliant "
        "crossovers) or 'cando' (isotropic baseline for comparison)",
    )
    mgcl2_M: float = Field(
        0.02,
        ge=0.0,
        le=1.0,
        description="MgCl₂ molarity (mol/L) setting the Debye length of the "
        "SNUPI inter-helix electrostatics; default 0.02 = 20 mM. "
        "snupi-only (ignored by 'cando').",
    )
    dynamics: bool = Field(
        False,
        description="Run Langevin structural DYNAMICS (thermal trajectory → "
        "time-mean shape + trajectory RMSF) instead of the static "
        "equilibrium solve (project_snupi_dynamics).",
    )
    hydrodynamics: bool = Field(
        False,
        description="Dynamics only: use the Rotne–Prager–Yamakawa coupled "
        "friction matrix vs diagonal Stokes drag.",
    )
    hydro_coarse_bp: Optional[int] = Field(
        None,
        ge=4,
        le=64,
        description="Hydrodynamics only: coarse-grain to ONE hydrodynamic bead "
        "per this many bp (blob RPY). The exact per-bp friction is a "
        "dense O(N²) matrix (~83 GB on a full M13 origami), so any "
        "large design must coarse-grain; 8 is the calibrated default. "
        "Minimum 4 — below that the blob is no bigger than a bead and "
        "the hydrodynamic coupling degenerates to Stokes. "
        "None = exact (refused up front if it would not fit).",
    )
    tails: bool = Field(
        False,
        description="Dynamics + snupi only: simulate the FREE ssDNA — overhangs, "
        "toeholds, dangling scaffold ends — as explicit one-bead-per-"
        "nucleotide Langevin chains and display them at their simulated "
        "positions (they are otherwise omitted and left at their "
        "rendered pose). A documented NADOC extension: published SNUPI "
        "cannot represent a free tail (it has no distal bp node). With "
        "hydrodynamics this requires hydro_coarse_bp.",
    )
    tail_max_nt: Optional[int] = Field(
        None,
        ge=1,
        le=200,
        description="Tails only: truncate each tail to at most this many "
        "nucleotides. None = the full tail.",
    )
    # Job-request annotations (C1/C2): anchors held fixed (Dirichlet BC) + a uniform E-field body
    # load, both threaded into predict_shape(...).  Never a topology edit (Three-Layer Law).
    anchors: Optional[list] = Field(
        None,
        description="Shared oxDNA anchor-scope descriptors "
        "(overhang/cluster/domain/strand/base) held fixed during the solve",
    )
    field: Optional[dict] = Field(
        None,
        description="Uniform E-field {field_pN, dir} — the same "
        "per-nucleotide force oxDNA applies; needs ≥1 anchor (COM drift)",
    )
    autostart: bool = Field(True)
    design_source_path: Optional[str] = Field(
        None, description="Workspace path of the active design"
    )


# ── Create / list / status ────────────────────────────────────────────────────


@router.post("/snupi/jobs")
async def create_snupi_job(body: CreateSnupiJobRequest) -> dict:
    """Prepare + run a new SNUPI FEM shape-prediction job from the active design."""
    design = design_state.get_or_404().without_reference_geometry()
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
    from backend.core.project_revisions import record_simulation_revision

    material = body.material if body.material in ("snupi", "cando") else "snupi"

    # Free ssDNA tails (SS-4) live in the Langevin engine ONLY, under the SNUPI material — they never
    # enter the static stiffness or the NMA (a floppy tail's near-zero eigenvalues would flood the
    # 200-mode RMSF basis).  And with hydrodynamics they need the coarse blob model, because they
    # carry their own smaller bead radius and the exact per-bp friction is single-radius.  Refuse
    # here with the fix, rather than let the detached worker die minutes in.
    if body.tails:
        if not body.dynamics:
            raise HTTPException(
                400,
                "Free ssDNA tails need Langevin dynamics — tick 'Langevin "
                "dynamics' as well (they are absent from the static solve).",
            )
        if material != "snupi":
            raise HTTPException(
                400,
                "Free ssDNA tails are a SNUPI-material extension; the CanDo "
                "baseline has no ssDNA chain model.",
            )
        if body.hydrodynamics and not body.hydro_coarse_bp:
            raise HTTPException(
                400,
                "Free ssDNA tails with hydrodynamics need the coarse blob model "
                "— choose a 'Coarse beads' value (the exact per-bp friction is "
                "single-radius and cannot carry the tails' smaller bead).",
            )

    # Preflight the RPY friction BEFORE spawning the detached worker. The friction is dense and O(N²)
    # in the FE node count (1 node/bp), so a full-size origami wants tens of GB; letting the worker try
    # drives the machine into swap and the OOM killer takes whatever is largest (in practice the user's
    # editor). Refuse here with the node count + the coarse-graining way out.
    if body.dynamics and body.hydrodynamics:
        from backend.physics.fem_solver import build_fem_mesh
        from backend.physics.snupi_hydro_coarse import blob_count
        from backend.physics.snupi_hydrodynamics import (
            HydroMemoryError,
            check_friction_memory,
        )

        mesh = build_fem_mesh(design, material=material)
        # Count the blobs for real. The coarse friction's only dense object is 6B×6B, and B is NOT
        # ⌈N/k⌉ — blobs never straddle a helix, so a design's helix boundaries fragment it upwards.
        # The ⌈N/k⌉ fallback therefore UNDERSTATES the cost, which is the wrong way for a guard whose
        # job is to stop the OOM killer taking the user's editor.
        nb = blob_count(mesh, body.hydro_coarse_bp) if body.hydro_coarse_bp else None
        try:
            check_friction_memory(len(mesh.nodes), body.hydro_coarse_bp, nb)
        except HydroMemoryError as exc:
            raise HTTPException(413, str(exc)) from exc

    job = new_snupi_job(
        design_name=name,
        nonlinear=body.nonlinear,
        n_steps=body.n_steps,
        with_rmsf=body.with_rmsf,
        material=material,
        mgcl2_M=body.mgcl2_M,
        dynamics=body.dynamics,
        hydrodynamics=body.hydrodynamics,
        hydro_coarse_bp=body.hydro_coarse_bp,
        tails=body.tails,
        tail_max_nt=body.tail_max_nt,
        anchors=body.anchors,
        field=body.field,
        n_nucleotides=len(_strand_nucleotide_order(design)),
        design_source_path=body.design_source_path,
        design_fingerprint=oxdna_design_fingerprint(design),
        feature_log_position=effective_feature_log_position(design),
        doc_id=doc_context.get_current_doc(),
    )
    provenance = record_simulation_revision(_workspace(), design, "snupi", job.job_id)
    job.project_id = provenance.project_id
    job.design_revision_id = provenance.revision_id
    job.status = SnupiStatus.preparing
    job.save(_workspace())
    logger.info(
        "create_snupi_job: job_id=%s design=%s nonlinear=%s material=%s",
        job.job_id,
        name,
        body.nonlinear,
        material,
    )

    try:
        await run_in_threadpool(prepare_snupi_job, design, job, _workspace())
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "create_snupi_job: prepare FAILED for %s: %s",
            job.job_id,
            exc,
            exc_info=True,
        )
        job.status = SnupiStatus.failed
        job.error = f"Preparation failed: {exc}"
        job.save(_workspace())
        return job.to_dict()

    job.status = SnupiStatus.queued
    job.save(_workspace())
    if body.autostart:
        start_job(job, _workspace())
    return job.to_dict()


@router.get("/snupi/jobs")
async def list_snupi_jobs() -> list[dict]:
    from backend.core.design_disk_usage import dir_size_bytes_cached

    ws = _workspace()
    jobs = [reconcile_snupi_status(j, ws) for j in SnupiJob.list_jobs(ws)]
    current_fp = _current_fingerprint()
    out: list[dict] = []
    for j in jobs:
        d = j.to_dict()
        d["out_of_date"] = _is_out_of_date(j, current_fp)
        d["size_bytes"] = dir_size_bytes_cached(j.job_dir(ws))
        # A RUNNING job carries its live fraction + ETA so the ONE master progress bar in the unified
        # Jobs card advances during the solve. Without this the card falls back to counting completed
        # STAGES — and a SNUPI job has exactly one stage, so it would sit at 0 % for the whole run and
        # jump to 100 % at the end (which is why this panel used to carry a second bar of its own).
        if d.get("status") == "running":
            try:
                from backend.core.snupi_runner import job_progress

                p = job_progress(j, ws)
                d["progress_fraction"] = round(float(p.get("overall") or 0.0), 4)
                d["eta_seconds"] = p.get("eta_seconds")
                d["phase"] = p.get("phase")
                # Fine detail (step / n_steps / rate / retry) so a long solve visibly ticks.
                for k in ("step", "n_steps", "steps_per_s", "attempt"):
                    if p.get(k) is not None:
                        d[k] = p[k]
            except Exception:  # noqa: BLE001 — progress is advisory, never sink the list
                pass
        out.append(d)
    return out


@router.get("/snupi/jobs/{job_id}")
async def get_snupi_job(job_id: str) -> dict:
    job = _load_job(job_id)
    d = job.to_dict()
    d["out_of_date"] = _is_out_of_date(job, _current_fingerprint())
    return d


@router.get("/snupi/jobs/{job_id}/progress")
async def get_snupi_progress(job_id: str) -> dict:
    job = _load_job(job_id)
    return job_progress(job, _workspace())


@router.get("/snupi/jobs/{job_id}/error-log")
async def get_snupi_error_log(job_id: str) -> dict:
    """Failure detail for the UI's 'Error log' popup."""
    job = _load_job(job_id)
    return {
        "job_id": job_id,
        "status": job.status.value,
        "error": job.error or "",
        "log": job.error or "(no error recorded)",
    }


# ── Control ───────────────────────────────────────────────────────────────────


@router.post("/snupi/jobs/{job_id}/start")
async def start_snupi_job(job_id: str) -> dict:
    job = _load_job(job_id)
    if is_running(job_id, _workspace()):
        return {"ok": True, "message": "Job already running"}
    if job.status in (SnupiStatus.running, SnupiStatus.completed):
        raise HTTPException(400, f"Job is {job.status.value} — cannot start")
    if job.stages:
        job.stages[0].status = "pending"
        job.stages[0].started_at = None
    job.status = SnupiStatus.running
    job.error = None
    job.save(_workspace())
    start_job(job, _workspace())
    return {"ok": True, "job_id": job_id, "status": "running"}


@router.post("/snupi/jobs/{job_id}/stop")
async def stop_snupi_job(job_id: str) -> dict:
    job = _load_job(job_id)
    stopped = stop_job(job_id, _workspace())
    if not stopped:
        if job.status == SnupiStatus.running:
            job.status = SnupiStatus.stopped
            job.save(_workspace())
        return {"ok": True, "message": "Job was not actively running"}
    return {"ok": True, "job_id": job_id, "status": "stopping"}


@router.delete("/snupi/jobs/{job_id}")
async def delete_snupi_job(job_id: str) -> dict:
    ws = _workspace()
    job = _load_job(job_id)
    if is_running(job_id, ws) or job.status == SnupiStatus.running:
        raise HTTPException(400, "Stop the SNUPI job before deleting it")
    from backend.core.job_archive import purge_index_entry

    jd = job.job_dir(ws)
    if jd.exists():
        shutil.rmtree(jd)
    purge_index_entry(ws, "snupi_jobs", job.job_id)
    return {"ok": True, "job_id": job_id}


# ── Display ───────────────────────────────────────────────────────────────────


@router.get("/snupi/jobs/{job_id}/snapshot-geometry")
async def get_snupi_snapshot_geometry(job_id: str) -> dict:
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
    from backend.core.snupi_runner import _load_snapshot_design

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


@router.get("/snupi/jobs/{job_id}/display")
async def get_snupi_display(job_id: str) -> dict:
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


@router.get("/snupi/jobs/{job_id}/display-bin")
async def get_snupi_display_bin(job_id: str) -> Response:
    """Columnar float32 sibling of ``display`` for interactive visualization."""
    job = _load_job(job_id)
    payload = await run_in_threadpool(load_display_bin, job.job_dir(_workspace()))
    if not payload:
        return Response(status_code=204)
    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers={"X-NADOC-Uncompressed-Length": str(len(payload))},
    )


@router.get("/snupi/jobs/{job_id}/rmsf")
async def get_snupi_rmsf(job_id: str) -> dict:
    """Per-bp RMSF (nm) for the flexibility map.  One entry per FEM (duplex-core) node:
    ``{helix_id, bp_index, rmsf_nm}``."""
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


@router.get("/snupi/jobs/{job_id}/trajectory")
async def get_snupi_trajectory(job_id: str) -> dict:
    """The dynamics thermal/reconfiguration TRAJECTORY for the animation toggle (dynamics jobs only).
    ``{keys:[[helix,bp,dir,copy],…], frames:[[6 floats/key],…], n_frames}`` — the same wire shape as
    oxDNA's /trajectory, so the frontend scrubber/player (``framesToUpdates``) is reused."""
    from backend.core.snupi_runner import load_trajectory

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


@router.get("/snupi/jobs/{job_id}/deviation")
async def get_snupi_deviation(job_id: str) -> dict:
    """Per-nucleotide deviation of the FEM-predicted shape from the design's intended
    (displayed) geometry + the global RMSD.  Uses the job's own design snapshot so the
    comparison matches what the FEM solved, not live editor state."""
    from backend.core.cando_deviation import compute_deviation
    from backend.core.snupi_runner import _load_snapshot_design

    job = _load_job(job_id)
    jd = job.job_dir(_workspace())
    cached = load_display(jd)
    if not cached or not cached.get("positions"):
        return {"job_id": job.job_id, "ready": False, "positions": []}
    design = _load_snapshot_design(jd)
    if design is None:
        raise HTTPException(
            500, f"SNUPI job {job_id!r} has no design snapshot to compare against"
        )

    result = await run_in_threadpool(compute_deviation, design, cached["positions"])
    return {"job_id": job.job_id, "ready": True, **result}


@router.get("/snupi/jobs/{job_id}/cylinders")
async def get_snupi_cylinders(job_id: str) -> dict:
    """CanDo-style "jointed cylinder" geometry of the predicted shape: per-helix axis
    tubes + crossover joint connectors, in the aligned display frame.  Uses the job's
    cached display positions + its own design snapshot (crossovers)."""
    from backend.core.cando_cylinders import axis_from_backbones, compute_cylinders
    from backend.core.snupi_runner import _load_snapshot_design

    job = _load_job(job_id)
    jd = job.job_dir(_workspace())
    cached = load_display(jd)
    if not cached or not cached.get("positions"):
        return {"job_id": job.job_id, "ready": False, "helices": [], "joints": []}
    design = _load_snapshot_design(jd)
    if design is None:
        raise HTTPException(
            500, f"SNUPI job {job_id!r} has no design snapshot for cylinders"
        )

    rmsf_cached = load_rmsf(jd)
    rmsf = rmsf_cached.get("rmsf") if rmsf_cached else None
    axis_nodes = cached.get("axis") or axis_from_backbones(cached["positions"], rmsf)
    result = await run_in_threadpool(compute_cylinders, design, axis_nodes, rmsf)
    return {"job_id": job.job_id, "ready": True, **result}


@router.get("/snupi/jobs/{job_id}/shape-source")
async def get_snupi_shape_source(job_id: str) -> dict:
    """The SNUPI source bundle for the cross-engine comparison card.

    Turns the job's cached FEM display frame + per-bp NMA RMSF into the shared
    ``{engine, descriptors, rmsf, shape_frame, field}`` bundle ``build_comparison_report``
    consumes — SNUPI's ABSOLUTE shape descriptors on the rigid dsDNA core + its free-free
    RMSF.  Uses the job's OWN design snapshot for the core mask.  Physical-layer only."""
    from backend.api.skip_twist_tuning import core_reference_geometry
    from backend.core.cando_shape_source import build_cando_shape_source
    from backend.core.snupi_runner import _load_snapshot_design

    job = _load_job(job_id)
    jd = job.job_dir(_workspace())
    cached = load_display(jd)
    if not cached or not cached.get("positions"):
        return {"job_id": job.job_id, "ready": False}
    design = _load_snapshot_design(jd)
    if design is None:
        raise HTTPException(
            500, f"SNUPI job {job_id!r} has no design snapshot to compare against"
        )

    rmsf_cached = load_rmsf(jd)
    rmsf = rmsf_cached.get("rmsf") if rmsf_cached else None
    reference = await run_in_threadpool(core_reference_geometry, design)
    bundle = await run_in_threadpool(
        build_cando_shape_source, cached["positions"], reference, rmsf=rmsf
    )
    bundle["engine"] = "snupi"
    ready = bundle["descriptors"] is not None
    return {"job_id": job.job_id, "ready": ready, **bundle}


@router.get("/snupi/available")
async def get_snupi_available() -> dict:
    """The SNUPI FEM solver runs in-process (scipy) — always available.  Mirrors
    /cando/available so the panel's availability check has a uniform shape."""
    return {"available": True, "solver": "native-fem"}
