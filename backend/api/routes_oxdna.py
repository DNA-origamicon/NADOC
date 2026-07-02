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
from pydantic import BaseModel, ConfigDict, Field

from backend.api import state as design_state
from backend.api.assembly import _WORKSPACE_DIR
from backend.core.oxdna_job import OxdnaJob, OxdnaStatus, new_oxdna_job
from backend.core.oxdna_protocol import (
    build_field_stage,
    build_production_stage,
    build_relaxation_stages,
    build_run_stage,
)
from backend.core.oxdna_runner import (
    _latest_relaxed_conf,
    _load_snapshot_design,
    find_oxdna,
    find_oxdna_anm,
    is_running,
    job_progress,
    load_stage_specs,
    oxdna_available,
    oxdna_supports_cuda,
    prepare_oxdna_job,
    reconcile_oxdna_status,
    start_job,
    stop_job,
)
from backend.physics.oxdna_interface import (
    DEFAULT_ANCHOR_STIFF,
    _strand_nucleotide_order,
    count_undefined_bases,
    designed_pair_complementarity,
    oxdna_backbone_site,
    pn_to_oxdna_force,
    read_configuration_unwrapped,
    resolve_anchor_particles,
    write_configuration,
    write_field_forces,
    write_run_forces,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["oxdna"])

# Minimum fraction of designed Watson-Crick pairs that must be sequence-complementary
# for an oxDNA relaxation to be worth starting.  A correctly-sequenced design reads
# ~0.99 (a few frayed ends aside); a stale-after-skip design reads ~0.27 (≈ random).
# 0.80 cleanly separates the two — nothing legitimate sits in between.
_MIN_PAIR_COMPLEMENTARITY = 0.80


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
    max_relax_retries:  int   = Field(3, ge=0, le=5,
                                      description="Auto-retry budget: if md_relax leaves the structure "
                                                  "not equil-ready (a backbone bond past oxDNA's FENE "
                                                  "cliff), re-run it with escalated parameters up to this "
                                                  "many times before failing. 0 → proceed straight to the "
                                                  "capped equil.")
    autostart:          bool  = Field(True)
    # Relax-on-a-surface: optional hard surface ({dir, offset_nm, stiff}) + fixed
    # strands held throughout relaxation.  NO electric field here — a field-relaxed
    # structure is not how it would settle, so the field is production-only.
    surface:            Optional[dict]     = Field(None)
    anchors:            list[dict]         = Field(default_factory=list)
    anchor_stiff:       float              = Field(DEFAULT_ANCHOR_STIFF, gt=0.0)
    design_source_path: Optional[str] = Field(None, description="Workspace path of the active design")


class ProductionRequest(BaseModel):
    steps: int = Field(5_000_000, ge=1000, le=200_000_000,
                       description="Unbiased MD production steps")


class AnchorRef(BaseModel):
    """An anchor selection: one cluster / domain / overhang held fixed during a
    field stage.  Accepts the frontend's camelCase keys (strandId/domainIndex)."""
    model_config = ConfigDict(populate_by_name=True)
    kind:         str
    id:           Optional[str] = None
    strand_id:    Optional[str] = Field(None, alias="strandId")
    domain_index: Optional[int] = Field(None, alias="domainIndex")


class FieldRequest(BaseModel):
    field_pN:     float = Field(..., gt=0.0, description="Force per nucleotide (pN)")
    dir:          list[float] = Field(..., min_length=3, max_length=3,
                                      description="Field direction (auto-normalized)")
    anchors:      list[AnchorRef] = Field(default_factory=list)
    steps:        int = Field(2_000_000, ge=1000, le=200_000_000,
                              description="Field MD steps")
    anchor_stiff: float = Field(DEFAULT_ANCHOR_STIFF, gt=0.0,
                                description="oxDNA trap stiffness per anchored nucleotide "
                                            "(default pins anchors effectively immobile)")


class FieldElement(BaseModel):
    """The electric-field element of a composed run (uniform per-nucleotide force)."""
    field_pN: float = Field(..., gt=0.0, description="Force per nucleotide (pN)")
    dir:      list[float] = Field(..., min_length=3, max_length=3,
                                  description="Field direction (auto-normalized)")


class SurfaceElement(BaseModel):
    """The hard-surface element of a composed run (one-sided repulsion plane).

    ``dir`` is the plane's outward normal (the structure rests on the side ``dir``
    points toward); the plane's absolute height is derived from the structure's
    extent along ``dir`` at run start, nudged by ``offset_nm``."""
    dir:       list[float] = Field(..., min_length=3, max_length=3)
    offset_nm: float = Field(0.0, description="nm of clearance the surface sits beyond "
                                              "the structure's lowest point")
    stiff:     float = Field(5.0, gt=0.0, description="Repulsion-plane stiffness (oxDNA units)")


class RunRequest(BaseModel):
    """A consolidated production run: unbiased MD plus any combination of an electric
    field, a hard surface, and anchor traps (each independent/optional).  Branches a
    child job seeded from the relaxed parent so runs can be fanned out + compared."""
    steps:        int = Field(2_000_000, ge=1000, le=200_000_000)
    field:        Optional[FieldElement] = None
    surface:      Optional[SurfaceElement] = None
    anchors:      list[AnchorRef] = Field(default_factory=list)
    anchor_stiff: float = Field(DEFAULT_ANCHOR_STIFF, gt=0.0)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _workspace() -> Path:
    return _WORKSPACE_DIR


def _design_ref_conf(job_dir: Path, design) -> Path:
    """Path to an origin-frame DESIGN-geometry configuration for a job, generated
    + cached as ``design_ref.dat``.  Used as the alignment reference for EVERY
    display path (relaxed display, flexibility map, trajectory, field run) so the
    relaxed structure always superposes onto the design pose at the origin.

    A CHILD job (production / field run) is seeded from its parent's relaxed
    ``last_conf.dat``, which the relaxation MD has diffused tens of nm off-origin,
    so the child's own ``conf.dat`` is NOT a valid design-pose reference (aligning
    to it displays the whole structure far below/away from the design).  This
    regenerates a clean origin-frame reference from the job's design snapshot.

    Geometry uses ``compact_skips=True`` to match exactly what ``prepare_oxdna_job``
    wrote into a root job's ``conf.dat`` (deletions collapsed to one bp), so a root
    job's alignment is byte-for-byte unchanged by routing through this helper."""
    ref = job_dir / "design_ref.dat"
    if not ref.exists():
        from backend.api.crud import _geometry_for_design
        write_configuration(design, _geometry_for_design(design, compact_skips=True), ref)
    return ref


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


# ── Out-of-date detection (design edited after a job was relaxed) ──────────────
# Derived fingerprints for OLD jobs (saved before design_fingerprint existed) are
# cached in-memory by job_id — a job's snapshot is frozen, so its fingerprint never
# changes; this lets the list flag legacy jobs stale without re-hashing every poll.
_DERIVED_FP_CACHE: dict[str, str] = {}


def _current_design_fingerprint() -> "str | None":
    """Fingerprint of the CURRENTLY active design (None if there is none)."""
    from backend.core.oxdna_staleness import current_active_design_fingerprint
    return current_active_design_fingerprint()


def _job_fingerprint(job: OxdnaJob) -> "str | None":
    """The job's creation fingerprint — the stored value, or (for a job saved before
    this field existed) one derived once from its frozen design.json snapshot."""
    if job.design_fingerprint:
        return job.design_fingerprint
    cached = _DERIVED_FP_CACHE.get(job.job_id)
    if cached is not None:
        return cached
    from backend.core.oxdna_staleness import oxdna_design_fingerprint
    snap = _load_snapshot_design(job.job_dir(_workspace()))
    if snap is None:
        return None
    fp = oxdna_design_fingerprint(snap)
    _DERIVED_FP_CACHE[job.job_id] = fp
    return fp


def _job_is_out_of_date(job: OxdnaJob, current_fp: "str | None") -> bool:
    from backend.core.oxdna_staleness import job_out_of_date
    return job_out_of_date(_job_fingerprint(job), current_fp)


def _assert_job_current(job: OxdnaJob) -> None:
    """Refuse (409) a live/production op when the design changed since this job was
    relaxed — otherwise it resolves the current design's selections against the job's
    frozen topology and crashes with an internal error.  The frontend turns this 409
    into the 'design has changed' roll-or-cancel popup."""
    if _job_is_out_of_date(job, _current_design_fingerprint()):
        raise HTTPException(
            409,
            "The design has changed since this job was relaxed. Roll the feature log "
            "back to the relaxation stage, or run a new relaxation, before running a "
            "live session or production.",
        )


def _lineage_jobs(job: OxdnaJob) -> list[OxdnaJob]:
    """The selected job's ancestor chain, ROOT first → … → selected, following
    ``parent_job_id``.  A field/production child is seeded from its parent's end
    state, so the whole chain is one continuous trajectory (relax → field1 →
    field2 → …).  Stops at the first missing/unloadable ancestor."""
    ws = _workspace()
    chain = [job]
    seen = {job.job_id}
    cur = job
    while cur.parent_job_id and cur.parent_job_id not in seen:
        try:
            parent = OxdnaJob.load(cur.parent_job_id, ws)
        except Exception:  # noqa: BLE001 — missing/torn ancestor: show what we have
            break
        chain.append(parent)
        seen.add(parent.job_id)
        cur = parent
    chain.reverse()
    return chain


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


def _composite_inputs(job: OxdnaJob):
    """Assemble (design, stages, ref) for a job's WHOLE-LINEAGE composite trajectory
    (root → … → selected, every stage in time order, numbered boundary labels).
    Shared by the trajectory + per-frame atomistic/surface routes. Returns
    (design, [], None) when no stage has written a trajectory yet.

    The whole lineage aligns to ONE origin frame (design geometry) — the same
    reference the field display uses, NOT the job's conf.dat (a field child's
    conf.dat is the parent's drifted relaxed structure, off-origin)."""
    from backend.core.models import Design

    jd = job.job_dir(_workspace())
    ws = _workspace()
    chain = _lineage_jobs(job)
    stages: list = []
    run_no = 0
    for j in chain:
        is_root = j.parent_job_id is None
        if not is_root:
            run_no += 1
        first_of_job = True
        for st in j.stages:
            files = _stage_trajectories(j.stage_dir(ws, st.name))
            for k, traj in enumerate(files):
                label = st.name if len(files) == 1 else f"{st.name} (part {k + 1})"
                marker = None
                if first_of_job and not is_root:
                    marker = f"→ {st.kind} {run_no}"
                    first_of_job = False
                stages.append((label, st.kind, traj, marker))
    if not stages:
        return None, [], None
    snap = jd / "design.json"
    if not snap.exists():
        raise HTTPException(500, "design.json snapshot missing for this job")
    design = Design.model_validate_json(snap.read_text())
    ref = _design_ref_conf(jd, design)
    return design, stages, ref


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

@router.post("/oxdna/jobs/estimate-disk")
async def estimate_oxdna_disk(body: CreateOxdnaJobRequest) -> dict:
    """Forecast the disk an oxDNA relaxation would write vs. free space.

    Best-effort — any error returns ``warn=False`` so the forecast never blocks a
    launch.  oxDNA prints a bounded number of configs, so this rarely warns; it
    still catches an already-near-full disk.
    """
    from backend.core.disk_guard import forecast, oxdna_run_output_bytes
    from backend.core.oxdna_protocol import print_conf_interval

    try:
        design = design_state.get_or_404()
        n_nt = len(_strand_nucleotide_order(design))
        specs = build_relaxation_stages(
            mc_steps=body.mc_steps, md_relax_steps=body.md_relax_steps,
            equil_steps=body.equil_steps)
        stages = [(s.steps, print_conf_interval(s)) for s in specs]
        predicted = oxdna_run_output_bytes(stages, n_nt)
    except Exception as exc:  # noqa: BLE001 — a forecast must never block a launch
        logger.warning("estimate_oxdna_disk failed (allowing launch): %s", exc)
        return {**forecast(_workspace(), 0), "skipped": True}
    return forecast(_workspace(), predicted)


@router.post("/oxdna/jobs/{job_id}/estimate-run-disk")
async def estimate_oxdna_run_disk(job_id: str, body: RunRequest) -> dict:
    """Forecast the disk an oxDNA production/run stage would write vs. free space."""
    from backend.core.disk_guard import forecast, oxdna_run_output_bytes

    job = _load_job(job_id)
    interval = max(1, int(body.steps) // 100)
    predicted = oxdna_run_output_bytes([(body.steps, interval)], job.n_nucleotides)
    return forecast(job.job_dir(_workspace()), predicted)


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

    # Complementarity check: every base may be defined (A/C/G/T) yet the staples
    # may not COMPLEMENT the scaffold at the paired positions — oxDNA only H-bonds
    # complementary bases (A-T/G-C), so a de-registered design relaxes to a low
    # base-pair ceiling and fails the health gate with a cryptic "N% retention".
    # The usual cause is adding/removing loops or skips on an already-sequenced
    # design: skips drop a nucleotide without consuming a sequence character, so
    # every downstream base shifts by one and the staple de-registers from the
    # scaffold (verified on 3x6x400_test: 150 skips dropped complementarity from
    # 99% to 27%).  Block with an actionable message instead of wasting the run.
    n_comp, n_pairs = designed_pair_complementarity(design)
    if n_pairs > 0 and n_comp / n_pairs < _MIN_PAIR_COMPLEMENTARITY:
        pct = round(100 * n_comp / n_pairs)
        raise HTTPException(
            400,
            f"Only {pct}% of base pairs are Watson-Crick complementary "
            f"({n_comp}/{n_pairs}) — the staple sequences do not match the scaffold "
            "at the paired positions, so oxDNA cannot bond them and the structure "
            "would relax to a low base-pair ceiling. This usually means sequences "
            "were assigned BEFORE loops/skips were added (adding a skip shifts every "
            "downstream base). Re-run Assign Sequences to re-derive them against the "
            "current structure, then start the relaxation.",
        )

    # Relax-on-a-surface elements (field excluded by design).
    surface_in = body.surface if (body.surface and float(body.surface.get("stiff", 0)) > 0) else None
    anchors_in = body.anchors or []
    relax_has_forces = bool(surface_in or anchors_in)

    # Proteins present → an ANM-oxDNA (DNANM) hybrid run on the fork binary.
    from backend.physics.oxdna_protein import has_proteins
    protein = has_proteins(design)

    # Fail fast on the classic broken state: a CUDA run requested but the binary
    # NADOC resolved is CPU-only (e.g. a conda/apt oxDNA on PATH).  oxDNA would
    # otherwise run the cheap MC stage and only abort the long MD stage with the
    # cryptic "Backend 'CUDA' not supported".  Point the user at the fix instead.
    if body.backend == "CUDA":
        run_bin = find_oxdna_anm() if protein else find_oxdna()
        if run_bin and not oxdna_supports_cuda(run_bin):
            engine = "ANM-oxDNA" if protein else "oxDNA"
            raise HTTPException(
                400,
                f"GPU (CUDA) run requested but the {engine} binary NADOC resolved "
                f"({run_bin}) is CPU-only — it has no CUDA backend, so the MD stage "
                f"would fail. Build a CUDA-enabled oxDNA (MD Engines panel → install, "
                f"or `cmake .. -DCUDA=ON -DCMAKE_CUDA_ARCHITECTURES=<arch>` in "
                f"~/oxDNA/build), or set $OXDNA_BIN to an existing CUDA build. To run "
                f"on CPU anyway (much slower), choose the CPU backend.",
            )

    specs = build_relaxation_stages(
        mc_steps           = body.mc_steps,
        md_relax_steps     = body.md_relax_steps,
        equil_steps        = body.equil_steps,
        backend            = body.backend,
        device             = body.device,
        salt_concentration = body.salt_concentration,
        min_bp_retained    = body.min_bp_retained,
        surface_present    = relax_has_forces,
        protein            = protein,
    )

    job = new_oxdna_job(
        design_name        = name,
        stages             = [s.to_status() for s in specs],
        device             = body.device,
        backend            = body.backend,
        salt_concentration = body.salt_concentration,
        design_source_path = body.design_source_path,
        max_relax_retries  = body.max_relax_retries,
        # Echo the relaxation conditions so selecting this job repopulates the
        # Advanced / Hard surface / Anchors cards with what the run used.
        run_config         = {
            "kind":               "relax",
            "backend":            body.backend,
            "device":             body.device,
            "salt_concentration": body.salt_concentration,
            "mc_steps":           body.mc_steps,
            "md_relax_steps":     body.md_relax_steps,
            "equil_steps":        body.equil_steps,
            "min_bp_retained":    body.min_bp_retained,
            "max_relax_retries":  body.max_relax_retries,
            "surface":            surface_in,
            "anchors":            anchors_in,
        },
    )
    job.status = OxdnaStatus.preparing
    job.save(_workspace())
    logger.info("create_oxdna_job: job_id=%s design=%s backend=%s", job.job_id, name, body.backend)

    # Build geometry + write the self-contained job dir (threadpool — file I/O).
    try:
        from backend.api.crud import _geometry_for_design
        # compact_skips=True: place flanking nucleotides one normal bp apart across
        # each deletion instead of leaving a 2×-rise gap, so oxDNA doesn't start with
        # backbone bonds stretched past its FENE divergence (~0.85 nm) at every skip.
        geometry = _geometry_for_design(design, compact_skips=True)
        # Count the nucleotides oxDNA actually simulates (the strand-order list),
        # NOT len(geometry): the geometry endpoint emits a slot for every position
        # in each helix's full lattice grid — including thousands of empty sites on
        # imported cadnano helices that span the whole grid — which over-counts the
        # real system size (e.g. 33,716 grid slots vs 14,774 actual nucleotides).
        job.n_nucleotides = len(_strand_nucleotide_order(design))
        # Out-of-date fingerprint + the feature-log point to roll back to if the
        # design is later edited (so live/production can be made consistent again).
        from backend.core.oxdna_staleness import (
            effective_feature_log_position, oxdna_design_fingerprint)
        job.design_fingerprint = oxdna_design_fingerprint(design)
        job.feature_log_position = effective_feature_log_position(design)
        await run_in_threadpool(
            prepare_oxdna_job, design, geometry, job, _workspace(), specs,
            surface=surface_in, anchors=anchors_in, anchor_stiff=body.anchor_stiff)
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
    from backend.core.design_disk_usage import dir_size_bytes_cached
    ws = _workspace()
    jobs = [reconcile_oxdna_status(j, ws) for j in OxdnaJob.list_jobs(ws)]
    current_fp = _current_design_fingerprint()   # computed once for the whole list
    out: list[dict] = []
    for j in jobs:
        d = j.to_dict()
        d["out_of_date"] = _job_is_out_of_date(j, current_fp)
        d["size_bytes"] = dir_size_bytes_cached(j.job_dir(ws))
        out.append(d)
    return out


@router.get("/oxdna/jobs/{job_id}")
async def get_oxdna_job(job_id: str) -> dict:
    job = _load_job(job_id)
    d = job.to_dict()
    d["out_of_date"] = _job_is_out_of_date(job, _current_design_fingerprint())
    return d


@router.get("/oxdna/jobs/{job_id}/error-log")
async def get_oxdna_error_log(job_id: str) -> dict:
    """Detailed failure log for the UI's "Error log" popup.

    Returns the job-level error string plus the raw oxDNA stdout/stderr log of the
    stage that failed (or, lacking a failed stage, the most recently started one),
    tail-capped so the payload stays small.  Also surfaces a small diagnostics
    block — the resolved binary and whether it is CUDA-capable vs the backend the
    run requested — because the most common oxDNA failure is exactly that mismatch
    (a CUDA run against a CPU-only binary).
    """
    job = _load_job(job_id)
    ws = _workspace()
    stages = job.stages or []

    # Prefer the failed stage; else the current stage; else the last that started.
    target = next((s for s in stages if s.status == "failed"), None)
    if target is None and 0 <= job.current_stage_idx < len(stages):
        target = stages[job.current_stage_idx]
    if target is None:
        target = next((s for s in reversed(stages) if s.status != "pending"), None)

    log_text, log_path, stage_name = "", None, None
    if target is not None:
        stage_name = target.name
        p = job.stage_dir(ws, target.name) / "oxdna.log"
        log_path = str(p)
        if p.is_file():
            raw = p.read_text(errors="replace")
            lines = raw.splitlines()
            if len(lines) > 400:                       # tail-cap huge logs
                lines = ["… (earlier output trimmed) …", *lines[-400:]]
            log_text = "\n".join(lines)
        else:
            log_text = "(no oxDNA log was written for this stage)"

    # Hybrid (protein) jobs run on the ANM fork binary; detect from the snapshot.
    protein = False
    try:
        from backend.physics.oxdna_protein import has_proteins
        protein = has_proteins(_load_snapshot_design(job.job_dir(ws)))
    except Exception:
        protein = False
    run_bin = find_oxdna_anm() if protein else find_oxdna()
    return {
        "job_id": job_id,
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "error": job.error or "",
        "stage": stage_name,
        "log": log_text,
        "log_path": log_path,
        "diagnostics": {
            "requested_backend": job.backend,
            "oxdna_bin": run_bin,
            "cuda_capable": oxdna_supports_cuda(run_bin) if run_bin else False,
        },
    }


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
    _assert_job_current(job)
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


@router.post("/oxdna/jobs/{job_id}/roll-design")
async def roll_oxdna_job_design(job_id: str) -> dict:
    """Restore the design to the EXACT state this job was run at (its frozen
    snapshot), saving the current edits as a "Return to latest" loadout branch.

    This is the robust "roll" used by the out-of-date guard: a feature-log seek can't
    reproduce sequences / manual edits the log doesn't capture (so the stale flag
    never cleared), but restoring the job's saved snapshot byte-for-byte makes the
    current design match the job again → the ⚠ clears and live/production is
    consistent.  The later edits live on in the returned ``return_loadout_id`` branch."""
    from backend.api.crud import roll_active_to_job_state

    job = _load_job(job_id)
    design = _load_snapshot_design(job.job_dir(_workspace()))
    if design is None:
        raise HTTPException(400, "This job has no saved design snapshot to roll back to.")
    name = job.design_name or "this job"
    return roll_active_to_job_state(design, job.feature_log_position, f"Latest — before viewing {name}")


@router.post("/oxdna/jobs/{job_id}/field")
async def append_oxdna_field(job_id: str, body: FieldRequest) -> dict:
    """Spawn an electric-field run as a CHILD job branched from a relaxed parent.

    Each field run is its own job seeded from the parent's end state (its
    ``conf.dat`` = the parent's latest ``last_conf``), so the user can fan out
    several independent field runs OR chain them — branching a fresh field run
    off a completed field child seeds from that child's final structure, giving a
    continuous relax → field1 → field2 → … lineage.  The child runs a single
    ``field``-kind stage with a uniform per-nucleotide force + anchor traps; it
    links to its parent via ``parent_job_id`` and records the field params in
    ``efield`` (for the list sub-item hover).

    Anchors are required: an unanchored uniform force nets a centre-of-mass drift
    that streams the whole structure across the periodic box."""
    parent = _load_job(job_id)
    if is_running(job_id) or parent.status != OxdnaStatus.completed:
        raise HTTPException(400, "An electric-field run requires a completed job to seed from.")
    _assert_job_current(parent)
    if find_oxdna() is None:
        raise HTTPException(400, "oxDNA binary not found.")
    if not body.anchors:
        raise HTTPException(
            400, "An electric-field run needs ≥1 anchor (without one the field "
            "just drifts the whole structure across the box).")

    ws = _workspace()
    pjd = parent.job_dir(ws)
    design = _load_snapshot_design(pjd)
    if design is None:
        raise HTTPException(500, "design.json snapshot missing; cannot resolve anchors.")
    relaxed_conf, _stage = _latest_relaxed_conf(parent, ws)
    if relaxed_conf is None:
        raise HTTPException(400, "No relaxed configuration to seed the field run from.")

    field_oxdna = pn_to_oxdna_force(body.field_pN)
    anchors = [a.model_dump(by_alias=False) for a in body.anchors]
    stage = build_field_stage(
        name="1_field", field_oxdna=field_oxdna, field_dir=body.dir,
        forces_file="field_forces.txt", steps=body.steps,
        backend=parent.backend, device=parent.device,
        salt_concentration=parent.salt_concentration,
    )
    child = new_oxdna_job(
        design_name=f"{parent.design_name} · field",
        stages=[stage.to_status()],
        n_nucleotides=parent.n_nucleotides, device=parent.device,
        backend=parent.backend, salt_concentration=parent.salt_concentration,
        design_source_path=parent.design_source_path, parent_job_id=parent.job_id,
        design_fingerprint=parent.design_fingerprint,
        feature_log_position=parent.feature_log_position,
        efield={"force_pN": body.field_pN, "force_oxdna": field_oxdna, "dir": list(body.dir)},
        run_config={
            "kind":    "field",
            "steps":   body.steps,
            "field":   {"field_pN": body.field_pN, "dir": list(body.dir)},
            "surface": None,
            "anchors": [a.model_dump(by_alias=True, exclude_none=True) for a in body.anchors],
        },
    )

    import json
    from dataclasses import asdict
    cjd = child.job_dir(ws)
    cjd.mkdir(parents=True, exist_ok=True)
    shutil.copy(pjd / "topology.top", cjd / "topology.top")
    shutil.copy(pjd / "design.json", cjd / "design.json")
    shutil.copy(relaxed_conf, cjd / "conf.dat")
    try:
        info = write_field_forces(
            cjd / "field_forces.txt", design, cjd / "conf.dat",
            field_oxdna=field_oxdna, field_dir=body.dir,
            anchors=anchors, anchor_stiff=body.anchor_stiff,
        )
    except ValueError as exc:
        shutil.rmtree(cjd, ignore_errors=True)
        raise HTTPException(400, str(exc))
    child.efield["n_anchored"] = info["n_anchored"]
    child.efield["anchor_keys"] = info["anchor_keys"]   # display aligns on these (positional frame)
    child.n_nucleotides = info["n_total"]
    (cjd / "stages_spec.json").write_text(json.dumps([asdict(stage)], indent=2))
    child.status = OxdnaStatus.queued
    child.save(ws)
    start_job(child, ws, [stage])
    return child.to_dict()


@router.post("/oxdna/jobs/{job_id}/run")
async def append_oxdna_run(job_id: str, body: RunRequest) -> dict:
    """Spawn a CONSOLIDATED production run as a child job branched from a relaxed
    parent.  The run is unbiased MD plus any combination of independently-enabled
    elements: an electric field, a hard surface (repulsion plane), and anchor traps.

    Like the E-field run, each call seeds a fresh child from the parent's end
    state, so the user can fan out runs (field-only / surface-only / both /
    +anchors) and compare them side by side, OR chain them — branching off a
    completed child seeds from that child's final structure for a continuous
    multi-run lineage.

    A field with no anchors is rejected: an unanchored uniform force nets a
    centre-of-mass drift that streams the whole structure across the periodic box."""
    parent = _load_job(job_id)
    if is_running(job_id) or parent.status != OxdnaStatus.completed:
        raise HTTPException(400, "A production run requires a completed relaxation job.")
    _assert_job_current(parent)
    if find_oxdna() is None:
        raise HTTPException(400, "oxDNA binary not found.")
    if body.field and not body.anchors:
        raise HTTPException(
            400, "An electric field needs ≥1 anchor (without one the field just "
            "drifts the whole structure across the box). Add a fixed strand in the "
            "Anchors card, or disable the field.")

    ws = _workspace()
    pjd = parent.job_dir(ws)
    design = _load_snapshot_design(pjd)
    if design is None:
        raise HTTPException(500, "design.json snapshot missing; cannot resolve anchors.")
    relaxed_conf, _stage = _latest_relaxed_conf(parent, ws)
    if relaxed_conf is None:
        raise HTTPException(400, "No relaxed configuration to seed the run from.")

    # Resolve the enabled elements into the writer's input dicts.
    field_in = None
    efield_rec = None
    if body.field:
        f_oxdna = pn_to_oxdna_force(body.field.field_pN)
        field_in = {"force_oxdna": f_oxdna, "dir": body.field.dir}
        efield_rec = {"dir": list(body.field.dir), "force_oxdna": f_oxdna,
                      "force_pN": body.field.field_pN}
    wall_in = None
    if body.surface:
        wall_in = {"dir": body.surface.dir, "offset_nm": body.surface.offset_nm,
                   "stiff": body.surface.stiff}
    anchors = [a.model_dump(by_alias=False) for a in body.anchors]
    has_forces = bool(field_in or wall_in or anchors)

    stage = build_run_stage(
        name="1_production", steps=body.steps,
        external_forces=has_forces,
        forces_file="run_forces.txt" if has_forces else None,
        efield=efield_rec,
        forces_meta={"has_field": bool(field_in), "has_surface": bool(wall_in)},
        # repulsion plane / anchor traps are absolute-coordinate forces → disable
        # oxDNA's COM diffusion-fix so it doesn't shift them into the structure.
        absolute_forces=bool(wall_in or anchors),
        backend=parent.backend, device=parent.device,
        salt_concentration=parent.salt_concentration,
    )

    label = " · ".join(
        x for x in ("field" if field_in else "", "surface" if wall_in else "",
                    "anchored" if anchors and not field_in else "") if x) or "production"
    child = new_oxdna_job(
        design_name=f"{parent.design_name} · {label}",
        stages=[stage.to_status()],
        n_nucleotides=parent.n_nucleotides, device=parent.device,
        backend=parent.backend, salt_concentration=parent.salt_concentration,
        design_source_path=parent.design_source_path, parent_job_id=parent.job_id,
        design_fingerprint=parent.design_fingerprint,
        feature_log_position=parent.feature_log_position,
        efield=efield_rec or {},
        run_config={
            "kind":    "run",
            "steps":   body.steps,
            "field":   {"field_pN": body.field.field_pN, "dir": list(body.field.dir)} if body.field else None,
            "surface": {"dir": body.surface.dir, "offset_nm": body.surface.offset_nm,
                        "stiff": body.surface.stiff} if body.surface else None,
            "anchors": [a.model_dump(by_alias=True, exclude_none=True) for a in body.anchors],
        },
    )

    import json
    from dataclasses import asdict
    cjd = child.job_dir(ws)
    cjd.mkdir(parents=True, exist_ok=True)
    shutil.copy(pjd / "topology.top", cjd / "topology.top")
    shutil.copy(pjd / "design.json", cjd / "design.json")
    shutil.copy(relaxed_conf, cjd / "conf.dat")

    info = {"n_anchored": 0, "n_total": parent.n_nucleotides, "anchor_keys": [],
            "field": None, "wall": None}
    if has_forces:
        try:
            info = write_run_forces(
                cjd / "run_forces.txt", design, cjd / "conf.dat",
                field=field_in, wall=wall_in, anchors=anchors,
                anchor_stiff=body.anchor_stiff,
            )
        except ValueError as exc:
            shutil.rmtree(cjd, ignore_errors=True)
            raise HTTPException(400, str(exc))
    if efield_rec is not None:
        child.efield["n_anchored"] = info["n_anchored"]
        child.efield["anchor_keys"] = info["anchor_keys"]
    child.n_nucleotides = info["n_total"]
    (cjd / "stages_spec.json").write_text(json.dumps([asdict(stage)], indent=2))
    child.status = OxdnaStatus.queued
    child.save(ws)
    start_job(child, ws, [stage])
    return child.to_dict()


class AnchorPreviewRequest(BaseModel):
    anchors: list[AnchorRef] = Field(default_factory=list)


@router.post("/oxdna/jobs/{job_id}/field/anchor-preview")
async def preview_oxdna_field_anchors(job_id: str, body: AnchorPreviewRequest) -> dict:
    """Resolve an anchor selection to particle counts WITHOUT starting a run.

    The gizmo colour/scale grades the anchor-bond tension
    ``T = (force/nt) × n_total / n_anchored`` (the quantity that actually blew up
    a field run — the net field force funnels through the held bonds).  ``n_total``
    the panel already knows (the parent job's ``n_nucleotides``); ``n_anchored``
    needs the same backend resolution the real run uses, so the panel calls this on
    every anchor add/clear (cheap; no oxDNA, no files)."""
    parent = _load_job(job_id)
    design = _load_snapshot_design(parent.job_dir(_workspace()))
    if design is None:
        raise HTTPException(500, "design.json snapshot missing; cannot resolve anchors.")
    anchors = [a.model_dump(by_alias=False) for a in body.anchors]
    particles, _keys = resolve_anchor_particles(design, anchors)
    return {
        "n_total": len(_strand_nucleotide_order(design)),
        "n_anchored": len(particles),
    }


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
    """Delete a job and ALL of its descendant runs (field/production children
    chain off their parent's end state — orphaning them would leave undeletable,
    design-detached jobs).  Cascades to any depth (relax → field1 → field2 → …).
    Refuses if the job or any descendant is still running."""
    ws = _workspace()
    job = _load_job(job_id)
    if is_running(job_id) or job.status == OxdnaStatus.running:
        raise HTTPException(400, "Stop the oxDNA job before deleting it")

    # Collect the full descendant subtree (children, grandchildren, …) so a chained
    # lineage is removed as a unit.
    all_jobs = OxdnaJob.list_jobs(ws)
    children_of: dict[str, list[OxdnaJob]] = {}
    for j in all_jobs:
        if j.parent_job_id:
            children_of.setdefault(j.parent_job_id, []).append(j)
    descendants: list[OxdnaJob] = []
    stack = list(children_of.get(job_id, []))
    while stack:
        d = stack.pop()
        descendants.append(d)
        stack.extend(children_of.get(d.job_id, []))

    for d in descendants:
        if is_running(d.job_id) or d.status == OxdnaStatus.running:
            raise HTTPException(
                400, f"Stop the running child run ({d.job_id}) before deleting its ancestor.")

    from backend.core.job_archive import purge_index_entry
    deleted: list[str] = []
    for j in (*descendants, job):
        jd = j.job_dir(ws)
        if jd.exists():
            shutil.rmtree(jd)
        purge_index_entry(ws, "oxdna_jobs", j.job_id)   # drop archived-job index entry if any
        deleted.append(j.job_id)
    return {"ok": True, "job_id": job_id, "deleted": deleted, "n_children": len(descendants)}


# ── Archive / unarchive ────────────────────────────────────────────────────────

class _ArchiveBody(BaseModel):
    dest_root: str   # parent directory; the job moves to <dest_root>/<job_id>


@router.post("/oxdna/jobs/{job_id}/archive", status_code=202)
async def archive_oxdna_job(job_id: str, body: _ArchiveBody) -> dict:
    """Start moving a job's folder to ``dest_root`` in the background (poll status)."""
    from backend.core import job_archive
    ws = _workspace()
    job = _load_job(job_id)
    if is_running(job_id) or job.status == OxdnaStatus.running:
        raise HTTPException(400, "Stop the oxDNA job before archiving it")
    try:
        job_archive.start_archive(job, ws, "oxdna_jobs", Path(body.dest_root))
    except (ValueError, FileExistsError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "job_id": job_id, "action": "archive"}


@router.post("/oxdna/jobs/{job_id}/unarchive", status_code=202)
async def unarchive_oxdna_job(job_id: str) -> dict:
    """Start moving an archived job's folder back into the workspace (poll status)."""
    from backend.core import job_archive
    ws = _workspace()
    job = _load_job(job_id)
    try:
        job_archive.start_unarchive(job, ws, "oxdna_jobs")
    except (ValueError, FileExistsError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "job_id": job_id, "action": "unarchive"}


@router.get("/oxdna/jobs/{job_id}/archive-status")
async def oxdna_archive_status(job_id: str) -> dict:
    from backend.core import job_archive
    return job_archive.task_status("oxdna_jobs", job_id) or {"state": "idle"}


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
    prod_idx = next((i for i, s in enumerate(job.stages)
                     if s.kind in ("production", "field")), None)
    if prod_idx is None:
        return {"ready": False, "reason": "no production or field run yet"}

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
    # Sampling stages whose trajectory the flexibility map pools: production runs
    # AND electric-field runs (a field child has a single `field` stage — its
    # trajectory is just as valid a fluctuation sample about the field-deflected
    # mean as a production run is about the relaxed mean).
    prod_stages = [s for s in job.stages if s.kind in ("production", "field")]
    if not prod_stages:
        return {"ready": False, "reason": "no production or field run yet"}

    jd = job.job_dir(_workspace())
    # Pool the trajectories of EVERY sampling run that has written frames —
    # done OR still running.  The map is available as soon as sampling has
    # started; short/in-progress runs are flagged via the confidence metric
    # below rather than blocked.
    usable = [s for s in prod_stages if s.status in ("done", "running")]
    trajs: list[Path] = []
    for s in usable:
        trajs.extend(_stage_trajectories(job.stage_dir(_workspace(), s.name)))
    if not trajs:
        return {"ready": False, "reason": "sampling starting — no frames yet"}

    # Reference = the origin-frame DESIGN geometry — IDENTICAL to the OxDNA display
    # route's Kabsch reference, so the flexibility map and the relaxed display sit
    # in the same place.  Must be _design_ref_conf (not the job's conf.dat): for a
    # field/production child conf.dat is the parent's drifted relaxed structure.
    design = Design.model_validate_json((jd / "design.json").read_text())
    ref_conf = _design_ref_conf(jd, design)

    result = await run_in_threadpool(production_rmsf, design, trajs, ref_conf)
    # Attach the confidence metric (frames pooled + statistical RMSF error) and
    # whether production is still running, so the panel can warn "preliminary".
    result["confidence"] = rmsf_confidence(result.get("n_frames", 0))
    result["production_running"] = any(s.status == "running" for s in prod_stages)
    return result


@router.get("/oxdna/jobs/{job_id}/deviation")
async def get_oxdna_deviation(job_id: str) -> dict:
    """Per-nucleotide DEVIATION map: the production mean structure recoloured by each
    base's distance (nm) from its DESIGNED position, after Kabsch superposition — the
    deviation counterpart of GET /oxdna/jobs/{id}/rmsf.  Available for ANY job with a
    production/field run (no autorefine required).  Returns ``{ready, positions:[{…,
    deviation}], min/max/mean_deviation, n_frames, confidence, production_running}``.
    """
    from backend.api.skip_twist_tuning import core_reference_geometry
    from backend.core.models import Design
    from backend.core.oxdna_health import (
        geometry_deviation_map, production_rmsf, rmsf_confidence,
    )

    job = _load_job(job_id)
    prod_stages = [s for s in job.stages if s.kind in ("production", "field")]
    if not prod_stages:
        return {"ready": False, "reason": "no production or field run yet"}
    jd = job.job_dir(_workspace())
    usable = [s for s in prod_stages if s.status in ("done", "running")]
    trajs: list[Path] = []
    for s in usable:
        trajs.extend(_stage_trajectories(job.stage_dir(_workspace(), s.name)))
    if not trajs:
        return {"ready": False, "reason": "sampling starting — no frames yet"}
    design = Design.model_validate_json((jd / "design.json").read_text())
    ref_conf = _design_ref_conf(jd, design)

    def _compute():
        mean = production_rmsf(design, trajs, ref_conf)
        if not mean.get("ready") or not mean.get("positions"):
            return None, mean
        return geometry_deviation_map(mean["positions"], core_reference_geometry(design)), mean

    dev, mean = await run_in_threadpool(_compute)
    if dev is None:
        return {"ready": False, "reason": "no frames yet"}
    dev["confidence"] = rmsf_confidence(mean.get("n_frames", 0))
    dev["production_running"] = any(s.status == "running" for s in prod_stages)
    return {"ready": True, "n_frames": mean.get("n_frames"), **dev}


@router.get("/oxdna/jobs/{job_id}/trajectory")
async def get_oxdna_trajectory(job_id: str) -> dict:
    """Composite scrub-able trajectory for the WHOLE lineage: every stage of the
    selected job AND all of its ancestors (relax → field1 → field2 → …), each
    frame PBC-unwrapped + Kabsch-aligned to the design reference, downsampled,
    with a labelled tick at every stage/run boundary.  A field/production child is
    seeded from its parent's end state, so the ancestor chain plays as one
    continuous trajectory.  Feeds the View-trajectory play/pause + slider.
    """
    from backend.core.oxdna_health import composite_trajectory

    job = _load_job(job_id)
    design, stages, ref = _composite_inputs(job)
    if not stages:
        return {"ready": False, "reason": "no trajectory yet"}
    result = await run_in_threadpool(composite_trajectory, design, stages, ref)
    return {"ready": result["n_frames"] > 0, **result}


@router.get("/oxdna/jobs/{job_id}/trajectory-meta")
async def get_oxdna_trajectory_meta(job_id: str) -> dict:
    """Frame count + stage markers for the composite trajectory WITHOUT downloading
    coordinates — lets the trajectory-keyframe slider size itself instantly. Indices
    match GET /oxdna/jobs/{id}/trajectory exactly."""
    from backend.core.oxdna_health import composite_trajectory_meta

    job = _load_job(job_id)
    design, stages, _ = _composite_inputs(job)
    if not stages:
        return {"ready": False, "reason": "no trajectory yet"}
    result = await run_in_threadpool(composite_trajectory_meta, design, stages)
    return {"ready": result["n_frames"] > 0, **result}


class OxdnaFramesAtomisticBody(BaseModel):
    frame_indices: list[int]


class OxdnaFramesSurfaceBody(BaseModel):
    frame_indices: list[int]
    color_mode: str = "strand"
    probe_radius: float = 0.28
    grid_spacing: float = 0.20
    radius_inflate: float = 1.30
    smooth: int = 15


@router.post("/oxdna/jobs/{job_id}/frames-atomistic")
async def oxdna_frames_atomistic(job_id: str, body: OxdnaFramesAtomisticBody) -> dict:
    """Per-frame ATOMISTIC coordinates for the given composite-trajectory frame
    indices (same wire format as /design/features/atomistic-batch). Used by the
    animation player to make the atomistic rep follow a trajectory keyframe.
    Heavy — one full all-atom rebuild per frame — so callers pass a downsampled
    index set. Indices match GET /oxdna/jobs/{id}/trajectory frame ordering."""
    from backend.core.oxdna_health import composite_trajectory_atomistic

    job = _load_job(job_id)
    design, stages, ref = _composite_inputs(job)
    if not stages:
        return {}
    return await run_in_threadpool(
        composite_trajectory_atomistic, design, stages, ref, body.frame_indices)


@router.post("/oxdna/jobs/{job_id}/frames-surface")
async def oxdna_frames_surface(job_id: str, body: OxdnaFramesSurfaceBody) -> dict:
    """Per-frame molecular SURFACE meshes for the given composite-trajectory frame
    indices (same wire format as /design/features/surface-batch). Heaviest path
    (all-atom rebuild + marching cubes per frame) — callers downsample hard."""
    from backend.core.oxdna_health import composite_trajectory_surface

    job = _load_job(job_id)
    design, stages, ref = _composite_inputs(job)
    if not stages:
        return {}
    return await run_in_threadpool(
        composite_trajectory_surface, design, stages, ref, body.frame_indices,
        body.color_mode, body.probe_radius, body.grid_spacing,
        body.radius_inflate, body.smooth)


def _relaxed_full_map(job, align: bool, *, copies: bool = False,
                      include_extra_bases: bool = False):
    """Shared relaxed-frame reader for the display + display-atomistic/surface
    routes. Returns ``(design, full_map, stage_name, conf_path, ref_conf)`` where
    ``full_map`` is ``{(hid,bp,dir): {backbone_position(CM), a1, a3}}`` — the same
    per-nucleotide shape the heavy-rep reconstruction consumes. ``full_map`` is
    None when no stage has a ``last_conf.dat`` yet.

    ``copies=True`` (atomistic/surface reconstruction only) additionally keys
    loop-insertion copies under their own 4-tuple key so the rigid-frame placer
    gives each copy its own relaxed frame.  The CG ``/display`` route keeps the
    default 3-tuple map (it unpacks ``(hid,bp,dir)``).

    ``include_extra_bases=True`` keeps crossover extra-base inserts (keyed
    ``(_XB_SENTINEL, crossover_id, k)``) so the display renders them at their real
    simulated positions instead of the geometric arc."""
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
        return (None, None, None, None, None)

    from backend.core.models import Design
    snap = jd / "design.json"
    if not snap.exists():
        raise HTTPException(500, "design.json snapshot missing for this job")
    design = Design.model_validate_json(snap.read_text())

    # Unwrap PBC, then align to the design location.  For a field run the ANCHORED
    # beads are a POSITIONAL-ONLY reference (translate the anchor onto its design
    # spot, NO rotation) so the field-induced reorientation we're studying stays
    # visible; otherwise the whole assembly is Kabsch-superposed (drift + tumbling
    # removed).  Either way the PBC unwrap stops the structure scattering off-screen.
    anchor_keys = (job.efield or {}).get("anchor_keys")
    # CRITICAL: align to the DESIGN geometry (origin frame), NOT the job's conf.dat
    # — for a field/production child conf.dat IS the parent's relaxation-drifted
    # last_conf (tens of nm off-origin), so aligning to it would render the
    # structure far from the design. _design_ref_conf is identical to a root job's
    # conf.dat, so root jobs are unaffected.
    ref_conf = _design_ref_conf(jd, design)
    if anchor_keys:
        full_map = read_configuration_unwrapped(
            conf_path, design, ref_conf,
            align_keys=[tuple(k) for k in anchor_keys], rotate=False, align=align,
            copies=copies, include_extra_bases=include_extra_bases)
    else:
        full_map = read_configuration_unwrapped(conf_path, design, ref_conf,
                                                align=align, copies=copies,
                                                include_extra_bases=include_extra_bases)
    return (design, full_map, stage_name, conf_path, ref_conf)


@router.get("/oxdna/jobs/{job_id}/display")
async def get_oxdna_display(job_id: str, align: bool = True) -> dict:
    """Return the last relaxed frame as an applyFemPositions update list.

    Reads the latest completed stage's ``last_conf.dat`` against the job's design
    snapshot.  ``nx/ny/nz`` carry the relaxed a1 (base-normal) so the deformed
    NADOC model orients faithfully.

    ``align=true`` (default) Kabsch-superposes the relaxed structure onto the
    design pose (drift + tumbling removed).  ``align=false`` shows it in its own
    simulation frame — how it actually settled (e.g. resting on a hard surface),
    lined up with the surface grid instead of re-posed onto the free design.
    """
    job = _load_job(job_id)
    design, full_map, stage_name, conf_path, ref_conf = _relaxed_full_map(
        job, align, include_extra_bases=True)
    if full_map is None:
        return {"job_id": job.job_id, "ready": False, "positions": [], "stage_name": None}

    # Hybrid (protein) jobs: a per-protein rigid 4×4 (design pose → relaxed pose in
    # the aligned display frame) the frontend applies to the protein render.
    proteins = []
    from backend.physics.oxdna_protein import has_proteins, protein_display_transforms
    if has_proteins(design):
        from backend.api.crud import _geometry_for_design
        transforms = protein_display_transforms(
            conf_path, ref_conf, design,
            _geometry_for_design(design, compact_skips=True), align=align)
        proteins = [{"attachment_id": aid, "transform": M} for aid, M in transforms.items()]
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
        "proteins": proteins,
    }


class OxdnaSurfaceBody(BaseModel):
    color_mode: str = "strand"
    probe_radius: float = 0.28
    grid_spacing: float = 0.20
    radius_inflate: float = 1.30
    smooth: int = 15


@router.post("/oxdna/jobs/{job_id}/display-atomistic")
async def get_oxdna_display_atomistic(job_id: str, align: bool = True) -> dict:
    """All-atom coordinates for the relaxed-display (last-frame) structure — the
    atomistic counterpart of GET /oxdna/jobs/{id}/display. Lets the OxDNA-display
    toggle drive the atomistic rep, not just CG beads. ``atomistic`` is a flat
    [x0,y0,z0,…] list in JOB-design atom-serial order.

    ``topology_hash`` identifies the JOB's design snapshot.  The flat positions are
    serial-indexed against the JOB topology — which may differ from the design now
    loaded in the app (edited after the job ran).  The frontend MUST compare this
    hash to the atoms it is rendering and rebuild from GET .../atomistic-model on a
    mismatch; blindly overlaying these positions on a different topology maps every
    serial to the wrong atom (scrambled colours/bonds/positions)."""
    from backend.core.oxdna_health import frame_atomistic_flat
    from backend.core.atomistic import atomistic_reference_topology_hash

    job = _load_job(job_id)
    design, full_map, stage_name, _, _ = _relaxed_full_map(job, align, copies=True, include_extra_bases=True)
    if full_map is None:
        return {"job_id": job.job_id, "ready": False}
    data = await run_in_threadpool(frame_atomistic_flat, design, full_map)
    return {"job_id": job.job_id, "ready": True, "stage_name": stage_name,
            "atomistic": data, "topology_hash": atomistic_reference_topology_hash(design),
            "n_atoms": len(data) // 3}


@router.get("/oxdna/jobs/{job_id}/atomistic-model")
async def get_oxdna_atomistic_model(job_id: str) -> dict:
    """The JOB design's full atomistic model (atoms + bonds, in design positions) so
    the frontend can REBUILD the renderer from the topology the relaxed positions
    belong to — when the app's loaded design has diverged from the job snapshot.
    Same serial space as display-atomistic's flat positions (both build from the job
    design), so a rebuild + applyPositionLerp aligns bond-for-bond."""
    from backend.core.atomistic import (build_atomistic_model, atomistic_to_json,
                                         atomistic_reference_topology_hash)
    from backend.core.models import Design
    job = _load_job(job_id)
    snap = job.job_dir(_workspace()) / "design.json"
    if not snap.exists():
        raise HTTPException(500, "design.json snapshot missing for this job")
    design = Design.model_validate_json(snap.read_text())
    model = await run_in_threadpool(build_atomistic_model, design)
    out = atomistic_to_json(model)
    out["topology_hash"] = atomistic_reference_topology_hash(design)
    return out


@router.post("/oxdna/jobs/{job_id}/display-surface")
async def get_oxdna_display_surface(job_id: str, body: OxdnaSurfaceBody,
                                    align: bool = True) -> dict:
    """Molecular surface mesh for the relaxed-display structure — the surface
    counterpart of GET /oxdna/jobs/{id}/display. ``surface`` = {vertices, faces,
    vertex_colors?} (same wire format as /design/features/surface-batch)."""
    from backend.core.oxdna_health import frame_surface_json

    job = _load_job(job_id)
    design, full_map, stage_name, _, _ = _relaxed_full_map(job, align, copies=True, include_extra_bases=True)
    if full_map is None:
        return {"job_id": job.job_id, "ready": False}
    data = await run_in_threadpool(
        frame_surface_json, design, full_map, body.color_mode, body.probe_radius,
        body.grid_spacing, body.radius_inflate, body.smooth)
    return {"job_id": job.job_id, "ready": True, "stage_name": stage_name, "surface": data}


@router.post("/oxdna/jobs/{job_id}/display-atomistic-audit")
async def get_oxdna_display_atomistic_audit(job_id: str, align: bool = True) -> dict:
    """Validation audit of the atomistic display for the relaxed-display frame — the
    programmatic counterpart of what the ball-and-stick / VDW representation DRAWS
    under the OxDNA-display toggle.  Every bond (stick) is measured + classified
    (rigid / linker / backbone / bridge); the report flags rigid-stamp violations
    (placer bugs — expect 0), over-stretched bonds (the long sticks on screen),
    bonds the renderer HIDES (>1 nm — drawn as nothing, but listed here so they are
    still queryable), atom clashes, and stranded atoms.  Same copy-aware relaxed
    frame the display-atomistic route uses, so the audited bonds ARE the rendered
    bonds (same serial pairs)."""
    from backend.core.atomistic_validation import audit_bonds

    job = _load_job(job_id)
    design, full_map, stage_name, _, _ = _relaxed_full_map(job, align, copies=True, include_extra_bases=True)
    if full_map is None:
        return {"job_id": job.job_id, "ready": False}
    report = await run_in_threadpool(audit_bonds, design, full_map)
    report.update({"job_id": job.job_id, "ready": True, "stage_name": stage_name})
    return report


class OxdnaTrajectoryAuditBody(BaseModel):
    frame_indices: list[int] | None = None
    max_audit: int = 8


@router.post("/oxdna/jobs/{job_id}/trajectory-audit")
async def get_oxdna_trajectory_audit(
        job_id: str, body: OxdnaTrajectoryAuditBody = OxdnaTrajectoryAuditBody()) -> dict:
    """Per-frame validation audit of the View-trajectory scrub — the programmatic
    counterpart of the atomistic display measured across a SAMPLING of composite
    trajectory frames (whole lineage), not just the single relaxed frame.  Each frame
    is reconstructed through the same shared sink the scrubber uses, so the settled
    invariants (rigid-stamp integrity, balanced forward/reverse phase, un-collapsed
    bases, preserved identity) are asserted to hold on EVERY frame.  ``frame_indices``
    audits exactly those composite-frame indices; omit it to evenly sample
    ``max_audit`` frames.  ``summary.all_invariants_ok`` is the pass signal."""
    from backend.core.atomistic_validation import audit_trajectory_frames

    job = _load_job(job_id)
    design, stages, ref = _composite_inputs(job)
    if not stages:
        return {"job_id": job.job_id, "ready": False, "reason": "no trajectory yet"}
    report = await run_in_threadpool(
        audit_trajectory_frames, design, stages, ref, body.frame_indices,
        max_audit=body.max_audit)
    report["job_id"] = job.job_id
    return report


def _rmsf_average_frame(job):
    """Shared average-structure reader for the rmsf-atomistic/surface routes.
    Returns ``(design, average_frame, rmsf_by_key)`` where ``average_frame`` is the
    per-nuc ``{key:{backbone_position(mean CM), a1, a3}}`` dict and ``rmsf_by_key``
    maps ``(helix_id, bp_index, direction) → rmsf`` (nm) so the surface can be
    coloured by flexibility.  Both are None when no sampling frames exist yet
    (mirrors GET /rmsf's not-ready paths)."""
    from backend.core.models import Design
    from backend.core.oxdna_health import production_rmsf

    prod_stages = [s for s in job.stages if s.kind in ("production", "field")]
    if not prod_stages:
        return (None, None, None)
    jd = job.job_dir(_workspace())
    usable = [s for s in prod_stages if s.status in ("done", "running")]
    trajs: list[Path] = []
    for s in usable:
        trajs.extend(_stage_trajectories(job.stage_dir(_workspace(), s.name)))
    if not trajs:
        return (None, None, None)
    design = Design.model_validate_json((jd / "design.json").read_text())
    ref_conf = _design_ref_conf(jd, design)
    result = production_rmsf(design, trajs, ref_conf, include_average_frame=True)
    if not result.get("ready"):
        return (design, None, None)
    rmsf_by_key = {
        (p["helix_id"], p["bp_index"], p["direction"]): p["rmsf"]
        for p in result.get("positions", [])
    }
    return (design, result.get("average_frame") or None, rmsf_by_key)


@router.post("/oxdna/jobs/{job_id}/rmsf-atomistic")
async def get_oxdna_rmsf_atomistic(job_id: str) -> dict:
    """All-atom coordinates for the flexibility-map AVERAGE structure — the
    atomistic counterpart of GET /oxdna/jobs/{id}/rmsf. Lets the flexibility-map
    toggle drive the atomistic rep."""
    from backend.core.oxdna_health import frame_atomistic_flat

    job = _load_job(job_id)
    design, frame, _ = await run_in_threadpool(_rmsf_average_frame, job)
    if frame is None:
        return {"job_id": job.job_id, "ready": False}
    data = await run_in_threadpool(frame_atomistic_flat, design, frame)
    return {"job_id": job.job_id, "ready": True, "atomistic": data}


@router.post("/oxdna/jobs/{job_id}/rmsf-surface")
async def get_oxdna_rmsf_surface(job_id: str, body: OxdnaSurfaceBody) -> dict:
    """Molecular surface for the flexibility-map AVERAGE structure — the surface
    counterpart of GET /oxdna/jobs/{id}/rmsf.  Always coloured by per-vertex RMSF
    (``vertex_rmsf``) so the mesh shows the same rigid→flexible ramp as the beads."""
    from backend.core.oxdna_health import frame_surface_json

    job = _load_job(job_id)
    design, frame, rmsf_by_key = await run_in_threadpool(_rmsf_average_frame, job)
    if frame is None:
        return {"job_id": job.job_id, "ready": False}
    data = await run_in_threadpool(
        frame_surface_json, design, frame, "rmsf", body.probe_radius,
        body.grid_spacing, body.radius_inflate, body.smooth, rmsf_by_key)
    return {"job_id": job.job_id, "ready": True, "surface": data}


@router.get("/oxdna/available")
async def get_oxdna_available() -> dict:
    """Probe for a usable oxDNA binary (mirror /md/namd-available)."""
    return oxdna_available()
