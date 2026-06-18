"""
oxDNA relaxation job routes — create, inspect, control, and display.

Sibling of ``routes_md.py`` (NAMD jobs).  All routes prefixed with /api.
Mounted in ``backend/api/main.py`` via ``app.include_router(..., prefix="/api")``.

Route summary
─────────────
POST   /oxdna/jobs                 create + prepare a 3-stage relaxation job
GET    /oxdna/jobs                  list all jobs
GET    /oxdna/jobs/{id}             single job status
GET    /oxdna/jobs/{id}/progress    overall + current-stage progress fractions
POST   /oxdna/jobs/{id}/start       start or resume a queued/stopped/failed job
POST   /oxdna/jobs/{id}/stop        stop a running job
DELETE /oxdna/jobs/{id}             delete job + generated files
GET    /oxdna/jobs/{id}/health      health.jsonl records
GET    /oxdna/jobs/{id}/metrics     metrics.jsonl records
GET    /oxdna/jobs/{id}/display     last relaxed frame → applyFemPositions list
GET    /oxdna/available             probe for a usable oxDNA binary

Display note: an oxDNA relaxation yields a single relaxed configuration (not a
trajectory), so /display returns the position+orientation update list directly
as JSON — the frontend feeds it straight to designRenderer.applyFemPositions.
oxDNA output is Physical-layer only; it never mutates Design topology.
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
from backend.core.oxdna_job import OxdnaJob, OxdnaStatus, new_oxdna_job
from backend.core.oxdna_protocol import build_production_stage, build_relaxation_stages
from backend.core.oxdna_runner import (
    find_oxdna,
    is_running,
    job_progress,
    load_stage_specs,
    oxdna_available,
    prepare_oxdna_job,
    reconcile_oxdna_status,
    start_job,
    stop_job,
)
from backend.physics.oxdna_interface import (
    count_undefined_bases,
    oxdna_backbone_site,
    read_configuration_unwrapped,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["oxdna"])


# ── Request models ────────────────────────────────────────────────────────────

class CreateOxdnaJobRequest(BaseModel):
    backend:            str   = Field("CUDA", description="'CUDA' or 'CPU' for the MD stages")
    device:             str   = Field("0", description="CUDA device index")
    salt_concentration: float = Field(0.5, gt=0.0, description="Molar salt for DNA2")
    mc_steps:           int   = Field(1_000,     ge=100,
                                      description="Stage 1 Monte Carlo relaxation steps (standard 10²–10⁴)")
    md_relax_steps:     int   = Field(1_000_000, ge=100,
                                      description="Stage 2 MD relaxation steps (standard ~1e6)")
    equil_steps:        int   = Field(100_000,   ge=100,
                                      description="Stage 3 short unbiased equilibration steps")
    min_bp_retained:    float = Field(0.50, ge=0.0, le=1.0,
                                      description="Base-pair retention gate for the MD relax/equil stages")
    autostart:          bool  = Field(True)
    design_source_path: Optional[str] = Field(None, description="Workspace path of the active design")


class ProductionRequest(BaseModel):
    steps: int = Field(5_000_000, ge=1000, le=200_000_000,
                       description="Unbiased MD production steps")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _workspace() -> Path:
    return _WORKSPACE_DIR


def _load_job(job_id: str) -> OxdnaJob:
    try:
        job = OxdnaJob.load(job_id, _workspace())
    except FileNotFoundError:
        raise HTTPException(404, f"oxDNA job {job_id!r} not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Failed to load job {job_id}: {exc}")
    # Recover a finished run whose runner thread died (e.g. backend restart) so
    # the completed production is recognised (Show RMSD / NAMD seed unlock).
    return reconcile_oxdna_status(job, _workspace())


def _stage_trajectories(stage_dir: Path) -> list[Path]:
    """All non-empty trajectory files for a stage, in CHRONOLOGICAL order.

    A resumed stage archives its prior partial trajectory as ``trajectory.r1.dat``
    (r2, …); the still-being-written run is ``trajectory.dat``.  Returns the
    archived parts first (oldest → newest) then the current file, so the composite
    player scrubs them in time order and the RMSF map pools every sampled frame
    (nothing lost to a resume)."""
    def _idx(p: Path) -> int:
        try:
            return int(p.name.split(".r")[1].split(".")[0])
        except (IndexError, ValueError):
            return 0
    parts = sorted(stage_dir.glob("trajectory.r*.dat"), key=_idx)
    out = [p for p in parts if p.stat().st_size > 0]
    cur = stage_dir / "trajectory.dat"
    if cur.exists() and cur.stat().st_size > 0:
        out.append(cur)
    return out


def _jsonl_records(path: Path) -> list[dict]:
    import json
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/oxdna/jobs")
async def create_oxdna_job(body: CreateOxdnaJobRequest) -> dict:
    """Prepare a new 3-stage oxDNA relaxation job from the active design.

    Preparation (write topology/conf/design snapshot) is fast — no solvation.
    """
    if body.backend not in {"CPU", "CUDA"}:
        raise HTTPException(400, f"Unknown backend: {body.backend!r}")
    if find_oxdna() is None:
        raise HTTPException(
            400,
            "oxDNA binary not found. Set $OXDNA_BIN or install to ~/oxDNA/build/bin/oxDNA.",
        )

    design = design_state.get_or_404()
    # Prefer the loaded file's name over design.metadata.name — a "save as" can
    # leave stale metadata (e.g. 6hb_OxDNA_test.nadoc still carries name
    # "6hb_primitive"), and the jobs list should show what the user opened.
    name = None
    if body.design_source_path:
        name = Path(body.design_source_path).stem or None
    name = (name or design.metadata.name or "design").replace(" ", "_")

    # Sequence check: oxDNA's DNA2 interaction needs a definite base (A/C/G/T) on
    # every nucleotide — any undefined ('N') base has no sequence-complementary
    # Watson-Crick partner, so that region melts during relaxation.  Block the job
    # if ANY base is still undefined (reference backdrop strands excluded, like
    # every other export path).  The frontend turns this 400 into a warning popup.
    undefined, _total = count_undefined_bases(design, exclude_reference=True)
    if undefined > 0:
        plural = "s" if undefined != 1 else ""
        raise HTTPException(
            400,
            f"Design has {undefined} undefined base{plural} — oxDNA needs every "
            "nucleotide assigned a definite base (A/C/G/T) with sequence-complementary "
            "Watson-Crick partners to hold the structure together during relaxation. "
            "Finish assigning sequences (a scaffold, e.g. M13mp18, plus all staple "
            "sequences) before starting an oxDNA relaxation.",
        )

    specs = build_relaxation_stages(
        mc_steps           = body.mc_steps,
        md_relax_steps     = body.md_relax_steps,
        equil_steps        = body.equil_steps,
        backend            = body.backend,
        device             = body.device,
        salt_concentration = body.salt_concentration,
        min_bp_retained    = body.min_bp_retained,
    )

    job = new_oxdna_job(
        design_name        = name,
        stages             = [s.to_status() for s in specs],
        device             = body.device,
        backend            = body.backend,
        salt_concentration = body.salt_concentration,
        design_source_path = body.design_source_path,
    )
    job.status = OxdnaStatus.preparing
    job.save(_workspace())
    logger.info("create_oxdna_job: job_id=%s design=%s backend=%s", job.job_id, name, body.backend)

    # Build geometry + write the self-contained job dir (threadpool — file I/O).
    try:
        from backend.api.crud import _geometry_for_design
        geometry = _geometry_for_design(design)
        job.n_nucleotides = len(geometry)
        await run_in_threadpool(prepare_oxdna_job, design, geometry, job, _workspace(), specs)
    except Exception as exc:  # noqa: BLE001
        logger.error("create_oxdna_job: prepare FAILED for %s: %s", job.job_id, exc, exc_info=True)
        job.status = OxdnaStatus.failed
        job.error = f"Preparation failed: {exc}"
        job.save(_workspace())
        return job.to_dict()

    job.status = OxdnaStatus.queued
    job.save(_workspace())

    if body.autostart:
        start_job(job, _workspace(), specs)

    return job.to_dict()


@router.get("/oxdna/jobs")
async def list_oxdna_jobs() -> list[dict]:
    return [
        reconcile_oxdna_status(j, _workspace()).to_dict()
        for j in OxdnaJob.list_jobs(_workspace())
    ]


@router.get("/oxdna/jobs/{job_id}")
async def get_oxdna_job(job_id: str) -> dict:
    return _load_job(job_id).to_dict()


@router.get("/oxdna/jobs/{job_id}/progress")
async def get_oxdna_progress(job_id: str) -> dict:
    job = _load_job(job_id)
    specs = load_stage_specs(job.job_dir(_workspace()))
    return job_progress(job, _workspace(), specs)


@router.post("/oxdna/jobs/{job_id}/start")
async def start_oxdna_job(job_id: str) -> dict:
    job = _load_job(job_id)
    if is_running(job_id):
        return {"ok": True, "message": "Job already running"}
    if job.status in (OxdnaStatus.running, OxdnaStatus.completed):
        raise HTTPException(400, f"Job is {job.status.value} — cannot start")
    if find_oxdna() is None:
        raise HTTPException(400, "oxDNA binary not found.")
    specs = load_stage_specs(job.job_dir(_workspace()))
    if not specs:
        raise HTTPException(500, "stages_spec.json missing; cannot resume this job.")
    job.status = OxdnaStatus.running
    job.error = None
    job.save(_workspace())
    start_job(job, _workspace(), specs)
    return {"ok": True, "job_id": job_id, "status": "running"}


@router.post("/oxdna/jobs/{job_id}/production")
async def append_oxdna_production(job_id: str, body: ProductionRequest) -> dict:
    """Append an unbiased MD production stage after a completed job.

    Available whenever the job is ``completed`` — the first time it continues from
    the relaxed structure; on a job that already has a production run it appends
    ANOTHER production stage that continues from the previous run's last frame
    (each run gets its own uniquely-named stage dir, so trajectories accumulate
    rather than overwrite).
    """
    job = _load_job(job_id)
    if is_running(job_id) or job.status != OxdnaStatus.completed:
        raise HTTPException(400, "Production requires a completed relaxation job.")
    if find_oxdna() is None:
        raise HTTPException(400, "oxDNA binary not found.")

    specs = load_stage_specs(job.job_dir(_workspace()))
    if not specs:
        raise HTTPException(500, "stages_spec.json missing; cannot append production.")
    # Unique stage name (1-based position prefix) so a re-run continues from the
    # previous stage's last_conf.dat instead of clobbering "4_production".
    prod = build_production_stage(
        name=f"{len(specs) + 1}_production",
        steps=body.steps, backend=job.backend, device=job.device,
        salt_concentration=job.salt_concentration,
    )
    specs.append(prod)

    # Persist the extended spec list + append the stage status; resume into it.
    from dataclasses import asdict
    import json
    (job.job_dir(_workspace()) / "stages_spec.json").write_text(
        json.dumps([asdict(s) for s in specs], indent=2)
    )
    job.stages.append(prod.to_status())
    job.current_stage_idx = len(specs) - 1
    job.status = OxdnaStatus.running
    job.error = None
    job.save(_workspace())
    start_job(job, _workspace(), specs)
    return {"ok": True, "job_id": job_id, "status": "running", "production_steps": body.steps}


@router.post("/oxdna/jobs/{job_id}/stop")
async def stop_oxdna_job(job_id: str) -> dict:
    job = _load_job(job_id)
    cancelled = stop_job(job_id, _workspace())
    if not cancelled:
        if job.status == OxdnaStatus.running:
            job.status = OxdnaStatus.stopped
            job.save(_workspace())
        return {"ok": True, "message": "Job was not actively running"}
    return {"ok": True, "job_id": job_id, "status": "stopping"}


@router.delete("/oxdna/jobs/{job_id}")
async def delete_oxdna_job(job_id: str) -> dict:
    job = _load_job(job_id)
    if is_running(job_id) or job.status == OxdnaStatus.running:
        raise HTTPException(400, "Stop the oxDNA job before deleting it")
    job_dir = job.job_dir(_workspace())
    if job_dir.exists():
        shutil.rmtree(job_dir)
    return {"ok": True, "job_id": job_id, "deleted": str(job_dir)}


@router.get("/oxdna/jobs/{job_id}/health")
async def get_oxdna_health(job_id: str) -> list[dict]:
    job = _load_job(job_id)
    return _jsonl_records(job.job_dir(_workspace()) / "health.jsonl")


@router.get("/oxdna/jobs/{job_id}/metrics")
async def get_oxdna_metrics(job_id: str) -> list[dict]:
    job = _load_job(job_id)
    return _jsonl_records(job.job_dir(_workspace()) / "metrics.jsonl")


@router.get("/oxdna/jobs/{job_id}/rmsd")
async def get_oxdna_rmsd(job_id: str) -> dict:
    """Per-frame backbone RMSD (nm) of the production run vs the relaxed structure.

    Only meaningful after a production stage has run.  Each production frame is
    PBC-unwrapped + Kabsch-aligned to the pre-production (relaxed) structure, so
    the RMSD reflects genuine internal deviation, not rigid-body diffusion.
    """
    from backend.core.models import Design
    from backend.core.oxdna_health import production_rmsd

    job = _load_job(job_id)
    prod_idx = next((i for i, s in enumerate(job.stages) if s.kind == "production"), None)
    if prod_idx is None:
        return {"ready": False, "reason": "no production run yet"}

    jd = job.job_dir(_workspace())
    traj = job.stage_dir(_workspace(), job.stages[prod_idx].name) / "trajectory.dat"
    if not traj.exists():
        return {"ready": False, "reason": "production trajectory not available yet"}

    # Reference = the stage immediately before production (the relaxed structure).
    ref_conf = jd / "conf.dat"
    if prod_idx > 0:
        cand = job.stage_dir(_workspace(), job.stages[prod_idx - 1].name) / "last_conf.dat"
        if cand.exists():
            ref_conf = cand

    design = Design.model_validate_json((jd / "design.json").read_text())
    result = await run_in_threadpool(production_rmsd, design, traj, ref_conf)
    return {"ready": result["n_frames"] > 0, **result}


@router.get("/oxdna/jobs/{job_id}/rmsf")
async def get_oxdna_rmsf(job_id: str) -> dict:
    """Per-nucleotide average position + RMSF over the production run — the
    flexibility map.  Each production frame is PBC-unwrapped + Kabsch-aligned to
    the SAME reference the OxDNA display uses (the job's ``conf.dat`` = the design
    geometry), so the average structure overlays the design in the exact same
    place/orientation as the relaxed-display toggle.  Every base's mean backbone
    position and its RMSF (root-mean-square fluctuation about that mean) are
    returned, so the panel can deform the model to the average structure
    recoloured rigid→flexible.

    Available as soon as a production run has STARTED (pools frames from done +
    running production stages).  Short/in-progress runs are not blocked — instead
    a ``confidence`` block (frames pooled + statistical RMSF error) and a
    ``production_running`` flag are returned so the panel can warn the user not to
    trust a short run.
    """
    from backend.core.models import Design
    from backend.core.oxdna_health import production_rmsf, rmsf_confidence

    job = _load_job(job_id)
    prod_stages = [s for s in job.stages if s.kind == "production"]
    if not prod_stages:
        return {"ready": False, "reason": "no production run yet"}

    jd = job.job_dir(_workspace())
    # Pool the trajectories of EVERY production run that has written frames —
    # done OR still running.  The map is available as soon as production has
    # started; short/in-progress runs are flagged via the confidence metric
    # below rather than blocked.
    usable = [s for s in prod_stages if s.status in ("done", "running")]
    trajs: list[Path] = []
    for s in usable:
        trajs.extend(_stage_trajectories(job.stage_dir(_workspace(), s.name)))
    if not trajs:
        return {"ready": False, "reason": "production starting — no frames yet"}

    # Reference = the job's conf.dat (design geometry) — IDENTICAL to the OxDNA
    # display route's Kabsch reference, so the flexibility map and the relaxed
    # display sit in the same place.
    ref_conf = jd / "conf.dat"

    design = Design.model_validate_json((jd / "design.json").read_text())
    result = await run_in_threadpool(production_rmsf, design, trajs, ref_conf)
    # Attach the confidence metric (frames pooled + statistical RMSF error) and
    # whether production is still running, so the panel can warn "preliminary".
    result["confidence"] = rmsf_confidence(result.get("n_frames", 0))
    result["production_running"] = any(s.status == "running" for s in prod_stages)
    return result


@router.get("/oxdna/jobs/{job_id}/trajectory")
async def get_oxdna_trajectory(job_id: str) -> dict:
    """Composite scrub-able trajectory: every stage that wrote a trajectory.dat
    (relaxation stages + all production runs), each frame PBC-unwrapped +
    Kabsch-aligned to the design reference, downsampled, with stage-boundary
    markers.  Feeds the View-trajectory play/pause + slider in the panel.
    """
    from backend.core.models import Design
    from backend.core.oxdna_health import composite_trajectory

    job = _load_job(job_id)
    jd = job.job_dir(_workspace())
    stages = []
    for st in job.stages:
        # Include any archived resume parts (trajectory.r1.dat …) before the
        # current trajectory.dat so a resumed stage scrubs in time order.
        files = _stage_trajectories(job.stage_dir(_workspace(), st.name))
        for k, traj in enumerate(files):
            label = st.name if len(files) == 1 else f"{st.name} (part {k + 1})"
            stages.append((label, st.kind, traj))
    if not stages:
        return {"ready": False, "reason": "no trajectory yet"}

    snap = jd / "design.json"
    if not snap.exists():
        raise HTTPException(500, "design.json snapshot missing for this job")
    design = Design.model_validate_json(snap.read_text())
    result = await run_in_threadpool(composite_trajectory, design, stages, jd / "conf.dat")
    return {"ready": result["n_frames"] > 0, **result}


@router.get("/oxdna/jobs/{job_id}/display")
async def get_oxdna_display(job_id: str) -> dict:
    """Return the last relaxed frame as an applyFemPositions update list.

    Reads the latest completed stage's ``last_conf.dat`` against the job's design
    snapshot.  ``nx/ny/nz`` carry the relaxed a1 (base-normal) so the deformed
    NADOC model orients faithfully.
    """
    job = _load_job(job_id)
    jd = job.job_dir(_workspace())

    # Pick the latest stage with a last_conf.dat (prefer the most-advanced done stage).
    conf_path = None
    stage_name = None
    for st in reversed(job.stages):
        cand = job.stage_dir(_workspace(), st.name) / "last_conf.dat"
        if cand.exists():
            conf_path = cand
            stage_name = st.name
            break

    if conf_path is None:
        return {"job_id": job.job_id, "ready": False, "positions": [], "stage_name": None}

    from backend.core.models import Design
    snap = jd / "design.json"
    if not snap.exists():
        raise HTTPException(500, "design.json snapshot missing for this job")
    design = Design.model_validate_json(snap.read_text())

    # Unwrap PBC + Kabsch-align to the design location (oxDNA wraps coords into the
    # box and the molecule diffuses/tumbles; raw coords scatter it off-screen).
    full_map = read_configuration_unwrapped(conf_path, design, jd / "conf.dat")
    # Render the true backbone site, not the oxDNA centre of mass — the CM sits
    # inward of the backbone, so rendering it collapses the apparent duplex.
    positions = [
        {
            "helix_id": hid,
            "bp_index": bp,
            "direction": direction,
            "backbone_position": oxdna_backbone_site(
                v["backbone_position"], v["a1"], v["a3"]).tolist(),
            "nx": float(v["a1"][0]),
            "ny": float(v["a1"][1]),
            "nz": float(v["a1"][2]),
        }
        for (hid, bp, direction), v in full_map.items()
    ]
    return {
        "job_id": job.job_id,
        "ready": True,
        "status": job.status.value,
        "stage_name": stage_name,
        "n_positions": len(positions),
        "positions": positions,
    }


@router.get("/oxdna/available")
async def get_oxdna_available() -> dict:
    """Probe for a usable oxDNA binary (mirror /md/namd-available)."""
    return oxdna_available()
