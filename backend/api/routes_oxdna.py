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
import asyncio
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.api import state as design_state
from backend.api.assembly import _WORKSPACE_DIR
from backend.core.oxdna_job import OxdnaJob, OxdnaStatus, new_oxdna_job
from backend.core.oxdna_protocol import (
    build_field_stage,
    build_production_stage,
    build_relaxation_stages,
    build_run_stage,
    DEFAULT_STEPS_PER_FRAME,
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
    _XB_SENTINEL,
    _strand_nucleotide_order,
    count_undefined_bases,
    is_extension_key,
    designed_pair_complementarity,
    max_crossover_backbone_stretch,
    oxdna_backbone_site,
    pn_to_oxdna_force,
    read_configuration_unwrapped,
    resolve_anchor_particles,
    write_configuration,
    write_field_forces,
    write_run_forces,
)
from backend.core.constants import NM_TO_OXDNA

logger = logging.getLogger(__name__)

router = APIRouter(tags=["oxdna"])

# Schema version for the cached simulation-surface payload. v2 added the per-vertex
# identity tables (vertex_strand_index* / vertex_nuc_index*) that per-cluster colour and
# opacity resolve against.
_SURF_PAYLOAD_V = 2

# Live frames-processed progress for the composite-trajectory build, keyed by job id.
# The build runs in a threadpool (off the event loop) so a concurrent poll of
# /trajectory-progress is served while it computes.  A plain dict assignment is
# GIL-atomic; the entry is created when the build starts and removed when it ends.
_TRAJ_PROGRESS: dict[str, dict] = {}
# Occupancy-cloud build progress. Separate from _TRAJ_PROGRESS on purpose — the two
# builds share a frame cache but not a progress bar, and one job can be doing both.
_OCC_PROGRESS: dict[str, dict] = {}
# Same idea for a trajectory-RANGE export build (POST /export-trajectory); kept separate from
# the view-trajectory build so an export and a scrub can't clobber each other's progress. Each
# entry carries a "phase" ('align' | 'write') the export card renders.
_EXPORT_PROGRESS: dict[str, dict] = {}


def _wall_axis_position_nm(wall_meta: dict) -> float:
    """World-axis coordinate of the resolved axis-aligned oxDNA plane."""
    direction = [float(x) for x in wall_meta.get("dir", (0, 1, 0))]
    axis_component = max(direction, key=abs)
    plane_scalar_nm = -float(wall_meta["position"]) / NM_TO_OXDNA
    return axis_component * plane_scalar_nm


# Minimum fraction of designed Watson-Crick pairs that must be sequence-complementary
# for an oxDNA relaxation to be worth starting.  A correctly-sequenced design reads
# ~0.99 (a few frayed ends aside); a stale-after-skip design reads ~0.27 (≈ random).
# 0.80 cleanly separates the two — nothing legitimate sits in between.
_MIN_PAIR_COMPLEMENTARITY = 0.80

# Non-blocking warning threshold: a capture-strand bead seeding this close to an origami
# bead (nm) means the user's hard-surface offset is too small for the strand height.
_CAPTURE_CLASH_WARN_NM = 1.0

# A skip-gap closing (compact_skips) is preferred UNLESS it lengthens the worst
# cross-helix backbone bond by more than this many oxDNA units versus the deformed
# geometry — i.e. it has desynced crossovers.  Skip gaps are intra-helix so they
# never affect crossover bonds; compaction can therefore only leave crossover stretch
# equal (balanced skips) or make it worse (a bent bundle's unequal per-helix skips),
# so any meaningful increase is unambiguous desync.  0.5 ignores numerical noise.
_COMPACT_CROSSOVER_MARGIN = 0.5


def _seed_geometry(design) -> list[dict]:
    """The per-nucleotide seed geometry oxDNA is initialised from.

    Deletions (skips) are normally collapsed to one bp (``compact_skips=True``) so
    oxDNA does not start with backbone bonds stretched across a 2×-rise gap at every
    skip.  But that compaction shifts EACH helix by its OWN cumulative deletion
    count, so on a *bent* bundle — paired helices carrying unequal skips/loops — it
    pulls every crossover between them axially apart (8+ oxDNA units vs ~2.5 for a
    registered one), which no relax can recover.  We compare the worst cross-helix
    backbone bond both ways and fall back to the un-compacted deformed geometry when
    compaction makes it meaningfully worse (the capped-force MC/MD stages then close
    the residual per-helix skip gaps).

    Physical layer only — this is the simulation's starting configuration, never
    written back into Design topology."""
    from backend.api.crud import _geometry_for_design

    # No skips/loops → compaction is a no-op; skip the second geometry build.
    if not any(h.loop_skips for h in design.helices):
        return _geometry_for_design(design, compact_skips=True)
    compact = _geometry_for_design(design, compact_skips=True)
    deformed = _geometry_for_design(design, compact_skips=False)
    compact_stretch = max_crossover_backbone_stretch(design, compact)
    deformed_stretch = max_crossover_backbone_stretch(design, deformed)
    if deformed_stretch < compact_stretch - _COMPACT_CROSSOVER_MARGIN:
        logger.info(
            "oxdna seed: compaction desynced crossovers (worst bond %.2f vs %.2f "
            "units) — using un-compacted deformed geometry instead",
            compact_stretch,
            deformed_stretch,
        )
        return deformed
    return compact


# ── Request models ────────────────────────────────────────────────────────────


class CreateOxdnaJobRequest(BaseModel):
    backend: str = Field("CUDA", description="'CUDA' or 'CPU' for the MD stages")
    device: str = Field("0", description="CUDA device index")
    salt_concentration: float = Field(0.5, gt=0.0, description="Molar salt for DNA2")
    mc_steps: int = Field(
        1_000,
        ge=100,
        description="Stage 1 Monte Carlo relaxation steps (standard 10²–10⁴)",
    )
    md_relax_steps: int = Field(
        1_000_000, ge=100, description="Stage 2 MD relaxation steps (standard ~1e6)"
    )
    equil_steps: int = Field(
        100_000, ge=100, description="Stage 3 short unbiased equilibration steps"
    )
    min_bp_retained: float = Field(
        0.50,
        ge=0.0,
        le=1.0,
        description="Base-pair retention gate for the MD relax/equil stages",
    )
    max_relax_retries: int = Field(
        3,
        ge=0,
        le=5,
        description="Auto-retry budget: if md_relax leaves the structure "
        "not equil-ready (a backbone bond past oxDNA's FENE "
        "cliff), re-run it with escalated parameters up to this "
        "many times before failing. 0 → proceed straight to the "
        "capped equil.",
    )
    autostart: bool = Field(True)
    # Relax-on-a-surface: optional hard surface ({dir, offset_nm, stiff}) + fixed
    # strands held throughout relaxation.  NO electric field here — a field-relaxed
    # structure is not how it would settle, so the field is production-only.
    surface: Optional[dict] = Field(None)
    anchors: list[dict] = Field(default_factory=list)
    anchor_stiff: float = Field(DEFAULT_ANCHOR_STIFF, gt=0.0)
    # Surface capture strands (immobilization): sim-only ssDNA strands complementary to the
    # overhangs, dispersed on the hard surface and built into the relaxed system.  Requires
    # `surface`.  Shape: surfaceStrandsSpec (sequence, attachEnd, shape, sizeNm, densityPerUm2,
    # offsetXNm/Y, seed, subjectToField).  See backend/physics/oxdna_surface_strands.py.
    surface_strands: Optional[dict] = Field(None)
    design_source_path: Optional[str] = Field(
        None, description="Workspace path of the active design"
    )


class ProductionRequest(BaseModel):
    steps: int = Field(
        5_000_000, ge=1000, le=200_000_000, description="Unbiased MD production steps"
    )


class AnchorRef(BaseModel):
    """An anchor selection held fixed during a field stage — one of: cluster,
    domain, overhang, a whole strand (``kind='strand'``, e.g. an overhang-binding
    oligo), a single base (``kind='base'`` at helix/bp/direction), a crossover's
    inserted extra base(s) (``kind='extra_base'``) or a strand extension's tail
    bead(s) (``kind='extension'``).  Accepts the frontend's camelCase keys
    (strandId/domainIndex/helixId/crossoverId/extensionId).

    NOTE this model is ``extra='ignore'`` (pydantic's default), so an unknown field
    is dropped SILENTLY rather than rejected — a descriptor carrying a field that is
    not declared here resolves to zero anchors with no error anywhere. Any new
    anchor kind must add its fields here in the same commit.
    """

    model_config = ConfigDict(populate_by_name=True)
    kind: str
    id: Optional[str] = None
    strand_id: Optional[str] = Field(None, alias="strandId")
    domain_index: Optional[int] = Field(None, alias="domainIndex")
    helix_id: Optional[str] = Field(None, alias="helixId")
    bp: Optional[int] = None
    direction: Optional[str] = None
    # Synthetic-bead scopes. `k` is the 5'→3' insert index (extra_base) or the tail
    # bead index (extension); None means the whole run/tail.
    crossover_id: Optional[str] = Field(None, alias="crossoverId")
    extension_id: Optional[str] = Field(None, alias="extensionId")
    k: Optional[int] = None


class FieldRequest(BaseModel):
    field_pN: float = Field(..., gt=0.0, description="Force per nucleotide (pN)")
    dir: list[float] = Field(
        ..., min_length=3, max_length=3, description="Field direction (auto-normalized)"
    )
    anchors: list[AnchorRef] = Field(default_factory=list)
    steps: int = Field(2_000_000, ge=1000, le=200_000_000, description="Field MD steps")
    anchor_stiff: float = Field(
        DEFAULT_ANCHOR_STIFF,
        gt=0.0,
        description="oxDNA trap stiffness per anchored nucleotide "
        "(default pins anchors effectively immobile)",
    )


class FieldElement(BaseModel):
    """The electric-field element of a composed run (uniform per-nucleotide force)."""

    field_pN: float = Field(..., gt=0.0, description="Force per nucleotide (pN)")
    dir: list[float] = Field(
        ..., min_length=3, max_length=3, description="Field direction (auto-normalized)"
    )


class SurfaceElement(BaseModel):
    """The hard-surface element of a composed run (one-sided repulsion plane).

    ``dir`` is the plane's outward normal (the structure rests on the side ``dir``
    points toward). ``position_nm`` is authoritative when supplied, keeping an
    immobilization surface fixed across serial runs. ``offset_nm`` is the legacy
    structure-relative placement used when no absolute position is supplied."""

    dir: list[float] = Field(..., min_length=3, max_length=3)
    offset_nm: float = Field(
        0.0,
        description="nm of clearance the surface sits beyond "
        "the structure's lowest point",
    )
    position_nm: Optional[float] = Field(
        None, description="fixed world-axis plane coordinate in nm"
    )
    stiff: float = Field(
        5.0, gt=0.0, description="Repulsion-plane stiffness (oxDNA units)"
    )


class RunRequest(BaseModel):
    """A consolidated production run: unbiased MD plus any combination of an electric
    field, a hard surface, and anchor traps (each independent/optional).  Branches a
    child job seeded from the relaxed parent so runs can be fanned out + compared."""

    steps: int = Field(2_000_000, ge=1000, le=200_000_000)
    # Steps between trajectory frames (oxDNA's print_conf_interval).  Absolute, not a
    # fraction of `steps`, so a longer run gives a LONGER trajectory rather than a
    # coarser one.  The submit card shows the resulting frame count + disk before launch.
    steps_per_frame: int = Field(
        DEFAULT_STEPS_PER_FRAME,
        ge=1,
        le=200_000_000,
        description="Simulation steps between saved trajectory frames",
    )
    field: Optional[FieldElement] = None
    surface: Optional[SurfaceElement] = None
    anchors: list[AnchorRef] = Field(default_factory=list)
    anchor_stiff: float = Field(DEFAULT_ANCHOR_STIFF, gt=0.0)
    # Capture strands are TOPOLOGY built into the relaxed parent (they must be present
    # through relaxation for the origami to hybridise to them), so a run can only inherit
    # and re-pin them.  This field is therefore INTENT, not a build request:
    #   {"enabled": true}                 → assert the parent carries capture beads; 409 if not.
    #   {"subjectToField": false}         → production-time force choice, overrides the parent's.
    # Omitted → inherit the parent's strands and its own subjectToField, unchanged.
    surface_strands: Optional[dict] = Field(None)


# ── Helpers ───────────────────────────────────────────────────────────────────


CAPTURE_STRANDS_NOT_BUILT = (
    "This relaxation was built without surface capture strands, and a production run "
    "can only inherit them \u2014 they are appended before relaxation so the origami "
    "hybridises to them as it settles. Start a new relaxation with capture strands "
    "enabled and run from that."
)


def capture_run_decision(parent_run_config, requested) -> dict:
    """PURE: what a production run does with its parent's surface capture strands.

    Capture strands are topology, not a production-time force: they are appended to the
    system BEFORE relaxation so the origami can hybridise to them while it settles (the
    Phase-2 "build, not overlay" decision).  A run branches off the relaxed parent by
    copying its topology/conf, so it can only inherit those beads and re-pin their
    attach-end traps \u2014 never add them to an origami-only structure.

    `requested` is therefore INTENT from the submit card, not a build request:
      * ``{"enabled": True}`` asserts the parent has capture strands.  If it does not,
        an ``error`` is returned so the caller refuses the run instead of quietly
        launching a strand-free one (which is what the UI used to do \u2014 the run
        started without them and the card's toggle flipped itself off).
      * ``{"subjectToField": bool}`` is a genuine production-time force choice (whether
        the uniform field sweeps the capture beads too), so an explicit value overrides
        whatever the parent was relaxed with.

    Returns ``{spec, trap_particles, n_beads, subject_to_field, error}``.  ``spec`` is
    the inherited spec stamped with the exclusion this run actually applies, so the card
    echoes back the RUN's setting rather than the parent's.
    """
    spec = (parent_run_config or {}).get("surface_strands") or {}
    built = spec.get("built") or {}
    trap_particles = built.get("trap_particles") or []
    n_beads = int(built.get("n_beads") or 0)
    req = requested or {}

    if req.get("enabled") and not trap_particles:
        return {
            "spec": None,
            "trap_particles": [],
            "n_beads": 0,
            "subject_to_field": True,
            "error": CAPTURE_STRANDS_NOT_BUILT,
        }

    subject = spec.get("subjectToField", spec.get("subject_to_field", True))
    if "subjectToField" in req:
        subject = bool(req["subjectToField"])
    return {
        "spec": {**spec, "subjectToField": subject} if spec else None,
        "trap_particles": trap_particles,
        "n_beads": n_beads,
        "subject_to_field": bool(subject),
        "error": None,
    }


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

    Geometry comes from ``_seed_geometry`` — the SAME seed ``prepare_oxdna_job``
    wrote into a root job's ``conf.dat`` (compacted, or un-compacted-deformed for a
    bent bundle) — so the display's Kabsch alignment matches the simulated frame."""
    ref = job_dir / "design_ref.dat"
    if not ref.exists():
        write_configuration(design, _seed_geometry(design), ref)
    return ref


# Single-flight for the atomistic display-bundle build: N concurrent first-clicks
# (or a warm-ahead racing a real click) for the SAME topology collapse to ONE build
# instead of stacking ~10 s / multi-GB builds.  Keyed by topology hash; the guard
# lock only protects the tiny per-key lookup, never the build itself.
_BUNDLE_BUILD_LOCKS: dict[str, asyncio.Lock] = {}
_BUNDLE_LOCKS_GUARD = asyncio.Lock()


async def _bundle_build_lock(thash: str) -> asyncio.Lock:
    async with _BUNDLE_LOCKS_GUARD:
        lk = _BUNDLE_BUILD_LOCKS.get(thash)
        if lk is None:
            lk = asyncio.Lock()
            _BUNDLE_BUILD_LOCKS[thash] = lk
        return lk


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
    if job.design_fingerprint and (
        job.design_fingerprint.startswith("v2:") or len(job.design_fingerprint) != 64
    ):
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
    into the 'design has changed' roll-or-cancel popup.

    Stands down for an UNATTENDED chain spawn: a chain stage seeds from this job's own
    frozen snapshot, not the loaded design, so which design is open is irrelevant (see
    ``md_chain_executor.in_unattended_chain_spawn``)."""
    from backend.core.md_chain_executor import in_unattended_chain_spawn

    if in_unattended_chain_spawn():
        return
    if _job_is_out_of_date(job, _current_design_fingerprint()):
        from backend.api import state as design_state
        from backend.core.oxdna_staleness import describe_staleness

        try:
            current = design_state.get_or_404()
        except Exception:  # noqa: BLE001 — staleness messaging must never 500
            current = None
        snap = _load_snapshot_design(job.job_dir(_workspace()))
        raise HTTPException(409, describe_staleness(snap, current, stage="relaxed"))


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


def _job_field(job: OxdnaJob) -> dict | None:
    """The electric field a job's stages ran under, as ``{dir:[x,y,z], field_pN}``,
    or ``None`` for a fieldless (relaxation / surface-only / plain-production) job.

    Prefers the ``run_config.field`` record (consolidated runs); falls back to the
    ``efield`` record older field children stored (``{force_pN, dir}``).  Used to tag
    each composite-trajectory stage so the View-trajectory arrow can follow the field
    direction of whichever run in a chain is on screen."""
    rc = job.run_config or {}
    f = rc.get("field")
    if (
        isinstance(f, dict)
        and isinstance(f.get("dir"), (list, tuple))
        and len(f["dir"]) == 3
    ):
        return {"dir": [float(x) for x in f["dir"]], "field_pN": f.get("field_pN")}
    ef = job.efield or {}
    if (
        isinstance(ef.get("dir"), (list, tuple))
        and len(ef["dir"]) == 3
        and ef.get("force_pN") is not None
    ):
        return {"dir": [float(x) for x in ef["dir"]], "field_pN": ef.get("force_pN")}
    return None


def _composite_inputs(job: OxdnaJob, scope: str = "lineage"):
    """Assemble (design, stages, ref) for a job's WHOLE-LINEAGE composite trajectory
    (root → … → selected, every stage in time order, numbered boundary labels).

    ``scope='job'`` restricts the stages to THIS job's own trajectories, dropping every
    ancestor — what the full-trajectory view uses so an uncapped frame budget covers one
    run rather than the whole chain.
    Shared by the trajectory + per-frame atomistic/surface routes. Returns
    (design, [], None) when no stage has written a trajectory yet.

    Each stage tuple is ``(label, kind, traj_path, marker_label, field)`` where
    ``field`` is the owning job's E-field descriptor (or None) — the trajectory
    player uses it to point the field arrow at whatever run in the chain is on screen.

    The whole lineage aligns to ONE origin frame (design geometry) — the same
    reference the field display uses, NOT the job's conf.dat (a field child's
    conf.dat is the parent's drifted relaxed structure, off-origin)."""
    from backend.core.models import Design

    jd = job.job_dir(_workspace())
    ws = _workspace()
    chain = [job] if scope == "job" else _lineage_jobs(job)
    stages: list = []
    run_no = 0
    for j in chain:
        is_root = j.parent_job_id is None
        if not is_root:
            run_no += 1
        first_of_job = True
        field = _job_field(j)
        for st in j.stages:
            files = _stage_trajectories(j.stage_dir(ws, st.name))
            for k, traj in enumerate(files):
                label = st.name if len(files) == 1 else f"{st.name} (part {k + 1})"
                marker = None
                if first_of_job and not is_root:
                    marker = f"→ {st.kind} {run_no}"
                    first_of_job = False
                stages.append((label, st.kind, traj, marker, field))
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
        design = design_state.get_or_404().without_reference_geometry()
        n_nt = len(_strand_nucleotide_order(design))
        specs = build_relaxation_stages(
            mc_steps=body.mc_steps,
            md_relax_steps=body.md_relax_steps,
            equil_steps=body.equil_steps,
        )
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
    predicted = oxdna_run_output_bytes(
        [(body.steps, max(1, int(body.steps_per_frame)))], job.n_nucleotides
    )
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

    design = design_state.get_or_404().without_reference_geometry()
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
    surface_in = (
        body.surface
        if (body.surface and float(body.surface.get("stiff", 0)) > 0)
        else None
    )
    anchors_in = body.anchors or []
    # Capture strands attach to the plane, so they require a hard surface; ignored without one.
    surface_strands_in = (
        body.surface_strands
        if (
            surface_in
            and body.surface_strands
            and body.surface_strands.get("enabled", True)
        )
        else None
    )
    relax_has_forces = bool(surface_in or anchors_in or surface_strands_in)

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
        mc_steps=body.mc_steps,
        md_relax_steps=body.md_relax_steps,
        equil_steps=body.equil_steps,
        backend=body.backend,
        device=body.device,
        salt_concentration=body.salt_concentration,
        min_bp_retained=body.min_bp_retained,
        surface_present=relax_has_forces,
        protein=protein,
    )

    job = new_oxdna_job(
        design_name=name,
        stages=[s.to_status() for s in specs],
        device=body.device,
        backend=body.backend,
        salt_concentration=body.salt_concentration,
        design_source_path=body.design_source_path,
        max_relax_retries=body.max_relax_retries,
        # Echo the relaxation conditions so selecting this job repopulates the
        # Advanced / Hard surface / Anchors cards with what the run used.
        run_config={
            "kind": "relax",
            "backend": body.backend,
            "device": body.device,
            "salt_concentration": body.salt_concentration,
            "mc_steps": body.mc_steps,
            "md_relax_steps": body.md_relax_steps,
            "equil_steps": body.equil_steps,
            "min_bp_retained": body.min_bp_retained,
            "max_relax_retries": body.max_relax_retries,
            "surface": surface_in,
            "anchors": anchors_in,
            "surface_strands": surface_strands_in,
        },
    )
    job.status = OxdnaStatus.preparing
    job.save(_workspace())
    logger.info(
        "create_oxdna_job: job_id=%s design=%s backend=%s",
        job.job_id,
        name,
        body.backend,
    )

    # Build geometry + write the self-contained job dir (threadpool — file I/O).
    try:
        # Compacted (skip gaps collapsed) so oxDNA doesn't start with backbone bonds
        # stretched across every deletion — but auto-falls back to the un-compacted
        # deformed geometry for a bent bundle, where compaction would desync
        # crossovers (see _seed_geometry).
        geometry = _seed_geometry(design)
        # Count the nucleotides oxDNA actually simulates (the strand-order list),
        # NOT len(geometry): the geometry endpoint emits a slot for every position
        # in each helix's full lattice grid — including thousands of empty sites on
        # imported cadnano helices that span the whole grid — which over-counts the
        # real system size (e.g. 33,716 grid slots vs 14,774 actual nucleotides).
        job.n_nucleotides = len(_strand_nucleotide_order(design))
        # Out-of-date fingerprint + the feature-log point to roll back to if the
        # design is later edited (so live/production can be made consistent again).
        from backend.core.oxdna_staleness import (
            effective_feature_log_position,
            oxdna_design_fingerprint,
        )

        job.design_fingerprint = oxdna_design_fingerprint(design)
        job.feature_log_position = effective_feature_log_position(design)
        forces_info = await run_in_threadpool(
            prepare_oxdna_job,
            design,
            geometry,
            job,
            _workspace(),
            specs,
            surface=surface_in,
            anchors=anchors_in,
            anchor_stiff=body.anchor_stiff,
            surface_strands=surface_strands_in,
        )
        # Persist the writer-resolved ABSOLUTE plane coordinate. The descriptor's
        # offset alone is insufficient after the structure moves or a trajectory is
        # scrubbed; visualization must render the exact plane oxDNA used at run start.
        wall_meta = (forces_info or {}).get("wall")
        if wall_meta and job.run_config.get("surface"):
            job.run_config["surface"]["position_nm"] = _wall_axis_position_nm(wall_meta)
        # Capture-strand build summary → run_config (for echo-back + production trap re-emission)
        # and a non-blocking clash warning if a capture bead seeds too close to the origami.
        cap = (forces_info or {}).get("capture")
        if cap and job.run_config.get("surface_strands") is not None:
            job.run_config["surface_strands"]["built"] = cap
            # The built system now has origami + capture particles; keep the job's count in
            # sync so trajectory frame parsing (and the stale-topology guard) see the real N.
            job.n_nucleotides += int(cap.get("n_beads", 0))
            md = cap.get("min_dist_to_origami_nm")
            if md is not None and md < _CAPTURE_CLASH_WARN_NM:
                cap["clash_warning"] = (
                    f"Surface capture strands seed as close as {md:.1f} nm to the origami — "
                    f"raise the hard-surface offset to avoid a t=0 clash."
                )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "create_oxdna_job: prepare FAILED for %s: %s",
            job.job_id,
            exc,
            exc_info=True,
        )
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
    current_fp = _current_design_fingerprint()  # computed once for the whole list
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
            if len(lines) > 400:  # tail-cap huge logs
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
        steps=body.steps,
        backend=job.backend,
        device=job.device,
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
    return {
        "ok": True,
        "job_id": job_id,
        "status": "running",
        "production_steps": body.steps,
    }


@router.post("/oxdna/jobs/{job_id}/roll-design")
async def roll_oxdna_job_design(job_id: str) -> dict:
    """Select the protected loadout backed by this job's frozen design snapshot."""
    from backend.api.crud import roll_active_to_job_state

    job = _load_job(job_id)
    design = _load_snapshot_design(job.job_dir(_workspace()))
    if design is None:
        raise HTTPException(
            400, "This job has no saved design snapshot to roll back to."
        )
    name = job.design_name or "this job"
    return roll_active_to_job_state(
        design,
        name,
        simulation_engine="oxdna",
        simulation_job_id=job.job_id,
    )


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

    Anchors are recommended but no longer required: an unanchored uniform force
    nets a centre-of-mass drift that streams the whole structure across the
    periodic box, so the UI shows a warning notice — but the run is allowed."""
    parent = _load_job(job_id)
    if is_running(job_id) or parent.status != OxdnaStatus.completed:
        raise HTTPException(
            400, "An electric-field run requires a completed job to seed from."
        )
    _assert_job_current(parent)
    if find_oxdna() is None:
        raise HTTPException(400, "oxDNA binary not found.")

    ws = _workspace()
    pjd = parent.job_dir(ws)
    design = _load_snapshot_design(pjd)
    if design is None:
        raise HTTPException(
            500, "design.json snapshot missing; cannot resolve anchors."
        )
    relaxed_conf, _stage = _latest_relaxed_conf(parent, ws)
    if relaxed_conf is None:
        raise HTTPException(400, "No relaxed configuration to seed the field run from.")

    field_oxdna = pn_to_oxdna_force(body.field_pN)
    anchors = [a.model_dump(by_alias=False) for a in body.anchors]
    stage = build_field_stage(
        name="1_field",
        field_oxdna=field_oxdna,
        field_dir=body.dir,
        forces_file="field_forces.txt",
        steps=body.steps,
        backend=parent.backend,
        device=parent.device,
        salt_concentration=parent.salt_concentration,
    )
    child = new_oxdna_job(
        design_name=f"{parent.design_name} · field",
        stages=[stage.to_status()],
        n_nucleotides=parent.n_nucleotides,
        device=parent.device,
        backend=parent.backend,
        salt_concentration=parent.salt_concentration,
        design_source_path=parent.design_source_path,
        parent_job_id=parent.job_id,
        design_fingerprint=parent.design_fingerprint,
        feature_log_position=parent.feature_log_position,
        efield={
            "force_pN": body.field_pN,
            "force_oxdna": field_oxdna,
            "dir": list(body.dir),
        },
        run_config={
            "kind": "field",
            "steps": body.steps,
            "field": {"field_pN": body.field_pN, "dir": list(body.dir)},
            "surface": None,
            "anchors": [
                a.model_dump(by_alias=True, exclude_none=True) for a in body.anchors
            ],
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
            cjd / "field_forces.txt",
            design,
            cjd / "conf.dat",
            field_oxdna=field_oxdna,
            field_dir=body.dir,
            anchors=anchors,
            anchor_stiff=body.anchor_stiff,
        )
    except ValueError as exc:
        shutil.rmtree(cjd, ignore_errors=True)
        raise HTTPException(400, str(exc))
    child.efield["n_anchored"] = info["n_anchored"]
    child.efield["anchor_keys"] = info[
        "anchor_keys"
    ]  # display aligns on these (positional frame)
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

    A field with no anchors is allowed: an unanchored uniform force nets a
    centre-of-mass drift that streams the whole structure across the periodic
    box, so the UI shows a warning notice — but the run is not blocked."""
    parent = _load_job(job_id)
    if is_running(job_id) or parent.status != OxdnaStatus.completed:
        raise HTTPException(
            400, "A production run requires a completed relaxation job."
        )
    _assert_job_current(parent)
    if find_oxdna() is None:
        raise HTTPException(400, "oxDNA binary not found.")

    ws = _workspace()
    pjd = parent.job_dir(ws)
    design = _load_snapshot_design(pjd)
    if design is None:
        raise HTTPException(
            500, "design.json snapshot missing; cannot resolve anchors."
        )
    relaxed_conf, _stage = _latest_relaxed_conf(parent, ws)
    if relaxed_conf is None:
        raise HTTPException(400, "No relaxed configuration to seed the run from.")

    # Resolve the enabled elements into the writer's input dicts.
    field_in = None
    efield_rec = None
    if body.field:
        f_oxdna = pn_to_oxdna_force(body.field.field_pN)
        field_in = {"force_oxdna": f_oxdna, "dir": body.field.dir}
        efield_rec = {
            "dir": list(body.field.dir),
            "force_oxdna": f_oxdna,
            "force_pN": body.field.field_pN,
        }
    wall_in = None
    if body.surface:
        wall_in = {
            "dir": body.surface.dir,
            "offset_nm": body.surface.offset_nm,
            "position_nm": body.surface.position_nm,
            "stiff": body.surface.stiff,
        }
    anchors = [a.model_dump(by_alias=False) for a in body.anchors]
    # Surface capture strands built into the relaxed parent are inherited via the copied
    # topology/conf; re-pin their attach ends so they stay tethered through production too.
    cap = capture_run_decision(parent.run_config, body.surface_strands)
    if cap["error"]:
        raise HTTPException(status_code=409, detail=cap["error"])
    cap_particles = cap["trap_particles"]
    cap_n_beads = cap["n_beads"]
    subject_caps = cap["subject_to_field"]
    field_exclude = (
        cap_n_beads if (field_in and cap_n_beads > 0 and not subject_caps) else 0
    )
    has_forces = bool(field_in or wall_in or anchors or cap_particles)

    stage = build_run_stage(
        name="1_production",
        steps=body.steps,
        external_forces=has_forces,
        forces_file="run_forces.txt" if has_forces else None,
        efield=efield_rec,
        forces_meta={"has_field": bool(field_in), "has_surface": bool(wall_in)},
        # repulsion plane / anchor / capture-strand traps are absolute-coordinate forces →
        # disable oxDNA's COM diffusion-fix so it doesn't shift them into the structure.
        absolute_forces=bool(wall_in or anchors or cap_particles),
        backend=parent.backend,
        device=parent.device,
        salt_concentration=parent.salt_concentration,
        steps_per_frame=body.steps_per_frame,
    )

    label = (
        " · ".join(
            x
            for x in (
                "field" if field_in else "",
                "surface" if wall_in else "",
                "anchored" if anchors and not field_in else "",
            )
            if x
        )
        or "production"
    )
    child = new_oxdna_job(
        design_name=f"{parent.design_name} · {label}",
        stages=[stage.to_status()],
        n_nucleotides=parent.n_nucleotides,
        device=parent.device,
        backend=parent.backend,
        salt_concentration=parent.salt_concentration,
        design_source_path=parent.design_source_path,
        parent_job_id=parent.job_id,
        design_fingerprint=parent.design_fingerprint,
        feature_log_position=parent.feature_log_position,
        efield=efield_rec or {},
        run_config={
            "kind": "run",
            "steps": body.steps,
            "field": {"field_pN": body.field.field_pN, "dir": list(body.field.dir)}
            if body.field
            else None,
            "surface": {
                "dir": body.surface.dir,
                "offset_nm": body.surface.offset_nm,
                "position_nm": body.surface.position_nm,
                "stiff": body.surface.stiff,
            }
            if body.surface
            else None,
            "anchors": [
                a.model_dump(by_alias=True, exclude_none=True) for a in body.anchors
            ],
            # Inherited spec, but stamped with the exclusion this run actually applied —
            # otherwise the card echoes back the parent's toggle, not the run's.
            "surface_strands": cap["spec"],
        },
    )

    import json
    from dataclasses import asdict

    cjd = child.job_dir(ws)
    cjd.mkdir(parents=True, exist_ok=True)
    shutil.copy(pjd / "topology.top", cjd / "topology.top")
    shutil.copy(pjd / "design.json", cjd / "design.json")
    shutil.copy(relaxed_conf, cjd / "conf.dat")

    info = {
        "n_anchored": 0,
        "n_total": parent.n_nucleotides,
        "anchor_keys": [],
        "field": None,
        "wall": None,
    }
    if has_forces:
        try:
            info = write_run_forces(
                cjd / "run_forces.txt",
                design,
                cjd / "conf.dat",
                field=field_in,
                wall=wall_in,
                anchors=anchors,
                anchor_stiff=body.anchor_stiff,
                field_exclude_trailing=field_exclude,
            )
        except ValueError as exc:
            shutil.rmtree(cjd, ignore_errors=True)
            raise HTTPException(400, str(exc))
        # Re-pin inherited capture strands at their (relaxed) attach positions, at the
        # covalent-stiff tether.  Appended to the same forces file the run reads.
        if cap_particles:
            from backend.physics.oxdna_interface import (
                read_cm_positions_oxdna,
                anchor_trap_block,
            )
            from backend.physics.oxdna_surface_strands import CAPTURE_TRAP_STIFF

            cm = read_cm_positions_oxdna(cjd / "conf.dat")
            blocks = [
                anchor_trap_block(p, cm[p], CAPTURE_TRAP_STIFF)
                for p in cap_particles
                if 0 <= p < len(cm)
            ]
            if blocks:
                with open(cjd / "run_forces.txt", "a", encoding="utf-8") as f:
                    f.write("\n" + "\n".join(blocks))
    if efield_rec is not None:
        child.efield["n_anchored"] = info["n_anchored"]
        child.efield["anchor_keys"] = info["anchor_keys"]
    child.n_nucleotides = info["n_total"]
    if info.get("wall") and child.run_config.get("surface"):
        child.run_config["surface"]["position_nm"] = _wall_axis_position_nm(
            info["wall"]
        )
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
        raise HTTPException(
            500, "design.json snapshot missing; cannot resolve anchors."
        )
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
    from backend.core.oxdna_job import descendants_of

    descendants = descendants_of(job_id, OxdnaJob.list_jobs(ws))

    for d in descendants:
        if is_running(d.job_id) or d.status == OxdnaStatus.running:
            raise HTTPException(
                400,
                f"Stop the running child run ({d.job_id}) before deleting its ancestor.",
            )

    from backend.core.job_archive import purge_index_entry

    deleted: list[str] = []
    for j in (*descendants, job):
        jd = j.job_dir(ws)
        if jd.exists():
            shutil.rmtree(jd)
        purge_index_entry(
            ws, "oxdna_jobs", j.job_id
        )  # drop archived-job index entry if any
        deleted.append(j.job_id)
    return {
        "ok": True,
        "job_id": job_id,
        "deleted": deleted,
        "n_children": len(descendants),
    }


# ── Archive / unarchive ────────────────────────────────────────────────────────


class _ArchiveBody(BaseModel):
    dest_root: str  # parent directory; the job moves to <dest_root>/<job_id>


@router.post("/oxdna/jobs/{job_id}/archive", status_code=202)
async def archive_oxdna_job(job_id: str, body: _ArchiveBody) -> dict:
    """Start moving a job's folder to ``dest_root`` in the background (poll status)."""
    from backend.core import job_archive

    ws = _workspace()
    job = _load_job(job_id)
    if is_running(job_id) or job.status == OxdnaStatus.running:
        raise HTTPException(400, "Stop the oxDNA job before changing its directory")
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
    prod_idx = next(
        (i for i, s in enumerate(job.stages) if s.kind in ("production", "field")), None
    )
    if prod_idx is None:
        return {"ready": False, "reason": "no production or field run yet"}

    jd = job.job_dir(_workspace())
    traj = job.stage_dir(_workspace(), job.stages[prod_idx].name) / "trajectory.dat"
    if not traj.exists():
        return {"ready": False, "reason": "production trajectory not available yet"}

    # Reference = the stage immediately before production (the relaxed structure).
    ref_conf = jd / "conf.dat"
    if prod_idx > 0:
        cand = (
            job.stage_dir(_workspace(), job.stages[prod_idx - 1].name) / "last_conf.dat"
        )
        if cand.exists():
            ref_conf = cand

    design = Design.model_validate_json((jd / "design.json").read_text())
    result = await run_in_threadpool(production_rmsd, design, traj, ref_conf)
    return {"ready": result["n_frames"] > 0, **result}


@router.get("/oxdna/jobs/{job_id}/rmsf")
async def get_oxdna_rmsf(job_id: str, align: bool = True) -> dict:
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
    from backend.core.oxdna_health import production_rmsf_cached, rmsf_confidence

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

    # copies=True → a per-loop-copy flexibility value so every loop bead recolours.
    cached = await run_in_threadpool(
        production_rmsf_cached,
        design,
        trajs,
        ref_conf,
        copies=True,
        align=align,
        n_trailing_extra=_capture_bead_count(job),
        trailing_extra_strand_length=_capture_strand_length(job),
    )
    # average_frame contains NumPy arrays for server-side reconstruction and is
    # intentionally retained only in the cache, not sent in the CG map payload.
    result = {k: v for k, v in cached.items() if k != "average_frame"}
    # Attach the confidence metric (frames pooled + statistical RMSF error) and
    # whether production is still running, so the panel can warn "preliminary".
    result["confidence"] = rmsf_confidence(result.get("n_frames", 0))
    result["production_running"] = any(s.status == "running" for s in prod_stages)
    return result


@router.get("/oxdna/jobs/{job_id}/deviation")
async def get_oxdna_deviation(job_id: str, align: bool = True) -> dict:
    """Per-nucleotide DEVIATION map: the production mean structure recoloured by each
    base's distance (nm) from its DESIGNED position, after Kabsch superposition — the
    deviation counterpart of GET /oxdna/jobs/{id}/rmsf.  Available for ANY job with a
    production/field run (no autorefine required).  Returns ``{ready, positions:[{…,
    deviation}], min/max/mean_deviation, n_frames, confidence, production_running}``.
    """
    from backend.api.skip_twist_tuning import core_reference_geometry
    from backend.core.models import Design
    from backend.core.oxdna_health import (
        geometry_deviation_map,
        production_rmsf_cached,
        rmsf_confidence,
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
        mean = production_rmsf_cached(
            design,
            trajs,
            ref_conf,
            copies=True,
            align=align,
            n_trailing_extra=_capture_bead_count(job),
            trailing_extra_strand_length=_capture_strand_length(job),
        )
        if not mean.get("ready") or not mean.get("positions"):
            return None, mean
        return geometry_deviation_map(
            mean["positions"], core_reference_geometry(design), align_output=align
        ), mean

    dev, mean = await run_in_threadpool(_compute)
    if dev is None:
        return {"ready": False, "reason": "no frames yet"}
    dev["confidence"] = rmsf_confidence(mean.get("n_frames", 0))
    dev["production_running"] = any(s.status == "running" for s in prod_stages)
    return {"ready": True, "n_frames": mean.get("n_frames"), **dev}


@router.get("/oxdna/jobs/{job_id}/strain")
async def get_oxdna_strain(
    job_id: str, metric: str = "backbone", align: bool = True
) -> dict:
    """Per-nucleotide LOCAL STRAIN map: the production mean structure recoloured by each
    base's time-averaged signed deviation from oxDNA2's equilibrium geometry, as a
    dimensionless fraction (0 = relaxed, + = stretched, − = compressed).  The strain
    sibling of GET /oxdna/jobs/{id}/deviation — deviation asks "is this base where the
    design put it", strain asks "is this base's own local geometry under load".

    The strain is measured per frame and THEN averaged (over up to
    ``oxdna_health._STRAIN_MAX_FRAMES`` evenly-sampled frames, reported as
    ``n_strain_frames``); straining the mean structure instead would collapse every
    bond.  Only the DISPLAY positions come from the mean structure.

    ``metric=backbone`` (default) — FENE backbone-bond strain: crossovers, skip/loop
    sites, forced connections and 5′/3′ extension tails the relaxation could not absorb.
    Covers every simulated particle, INCLUDING extension tails and crossover extra bases
    (they are the most FENE-fragile bonds in a design, so the map exists to find them).
    ``metric=wc`` — Watson–Crick base-pair stretch: melted / opening / mis-registered
    pairs.  Unpaired nucleotides (ssDNA loops, overhangs, extension tails, extra bases,
    ragged ends) have no designed partner and are omitted.

    Returns ``{ready, positions:[{…, strain}], min/max/mean/abs_max_strain, metric,
    unit, r0_units, n_frames, confidence, production_running}``.  Read-only over the
    Physical layer.
    """
    from backend.core.models import Design
    from backend.core.oxdna_health import (
        production_strain_field_cached,
        rmsf_confidence,
        strain_map,
    )

    if metric not in ("backbone", "wc"):
        raise HTTPException(
            400, f"unknown strain metric {metric!r} (expected 'backbone' or 'wc')"
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
        # ONE bounded trajectory walk does everything: the per-frame strain average AND the
        # mean frame the beads are drawn at.  It deliberately does NOT reuse
        # production_rmsf_cached's `average_frame`: that walks EVERY frame (805 on a real
        # job) and dominated this route's cost — 16.5 min of a 16.9 min response, against
        # 21 s for the strain walk itself.  The two mean frames are the same estimator over
        # the same aligned ensemble, differing only by sampling noise (~RMSF/√60, well under
        # 0.1 nm even in floppy regions), and the strain walk's is arguably the better one
        # because it also drops torn-unwrap frames.  Positions therefore still coincide with
        # the flexibility/deviation overlays to far below anything visible.
        avg = production_strain_field_cached(
            design,
            trajs,
            ref_conf,
            metric=metric,
            copies=True,
            align=align,
            n_trailing_extra=_capture_bead_count(job),
            trailing_extra_strand_length=_capture_strand_length(job),
        )
        if not avg["field"]:
            return None, avg
        return strain_map(design, avg["frame"], metric=metric, field=avg["field"]), avg

    strain, avg = await run_in_threadpool(_compute)
    n_strain_frames = avg.get("n_frames", 0)
    rejected = float(avg.get("rejected_fraction", 0.0))
    n_rejected = int(avg.get("n_rejected", 0))
    if strain is None:
        return {
            "ready": False,
            "reason": (
                "no frames yet"
                if not n_strain_frames
                else "no paired bases to measure"
                if metric == "wc"
                else "no backbone bonds to measure"
            ),
        }
    strain["confidence"] = rmsf_confidence(n_strain_frames)
    strain["n_strain_frames"] = n_strain_frames
    strain["rejected_fraction"] = rejected
    strain["n_rejected"] = n_rejected
    strain["n_frames_torn"] = int(avg.get("n_frames_torn", 0))
    strain["production_running"] = any(s.status == "running" for s in prod_stages)
    return {"ready": True, "n_frames": n_strain_frames, **strain}


@router.get("/oxdna/jobs/{job_id}/shape-source")
async def get_oxdna_shape_source(job_id: str, align: bool = True) -> dict:
    """oxDNA source bundle for the cross-engine comparison card (S5) — the ``engine=
    "oxdna"`` column that is the reference for relaxed SHAPE.  Returns ``{ready,
    stage_name, engine, descriptors, rmsf, shape_frame, field}``: shared shape descriptors
    (twist / bend / Rg / end-to-end) computed on the relaxed frame + the per-nucleotide
    RMSF profile when a production/field run has frames.

    Reads the latest relaxed frame (the SAME frame the /display toggle shows) and, from
    any production/field stage with frames, its RMSF map, then core-filters BOTH to the
    rigid dsDNA core (ssDNA ends dropped) with the same mask the metrics card uses.  The
    descriptors are computed with the SAME locked oxdna_health estimators, but report
    oxDNA's ABSOLUTE twist/bend on the relaxed frame (the cross-engine-comparable value) —
    NOT the differential (measured − analytic) twist/curvature the Graphs-&-Metrics card
    plots over the production trajectory, so those numbers won't be equal.  RMSF is
    optional: a job with only a relaxation run still supplies the shape column.  All
    outputs are Physical-layer/display only (Three-Layer Law)."""
    from backend.api.skip_twist_tuning import core_reference_geometry
    from backend.core.oxdna_health import production_rmsf_cached
    from backend.core.oxdna_shape_source import build_oxdna_shape_source

    job = _load_job(job_id)
    design, full_map, stage_name, _conf_path, ref_conf = _relaxed_full_map(job, align)
    if full_map is None:
        return {"ready": False, "reason": "no relaxed frame yet"}

    # Render the true backbone site (not the oxDNA centre of mass) — identical to /display.
    shape_frame = [
        {
            "helix_id": k[0],
            "bp_index": k[1],
            "direction": k[2],
            "backbone_position": oxdna_backbone_site(
                v["backbone_position"], v["a1"], v["a3"]
            ).tolist(),
        }
        for k, v in full_map.items()
    ]

    # RMSF (per-nt trajectory-variance flexibility) from whichever sampling stage has
    # frames.  Prefer a production/field run; a relaxation-only job (no production stage)
    # falls back to its EQUILIBRATION run — MD sampling at the target conditions, a valid
    # flexibility ensemble (mirrors mrDNA's use of its CG-relaxation trajectory for RMSF),
    # then the MD-relax stage.  So the oxDNA column appears in the comparison card's RMSF
    # overlay for relaxation-only jobs, not only production runs.  Optional — the shape
    # column stands on the relaxed frame alone when no dynamics stage has frames.
    rmsf_positions = None
    n_frames = None
    trajs: list[Path] = []
    for kinds in (("production", "field"), ("equil",), ("md_relax",)):
        stages = [
            s for s in job.stages if s.kind in kinds and s.status in ("done", "running")
        ]
        for s in stages:
            trajs.extend(_stage_trajectories(job.stage_dir(_workspace(), s.name)))
        if trajs:
            break
    if trajs:
        res = await run_in_threadpool(
            production_rmsf_cached,
            design,
            trajs,
            ref_conf,
            n_trailing_extra=_capture_bead_count(job),
            trailing_extra_strand_length=_capture_strand_length(job),
        )
        if res.get("ready"):
            rmsf_positions = res["positions"]
            n_frames = res.get("n_frames")

    core_ref = core_reference_geometry(design)
    source = build_oxdna_shape_source(
        shape_frame, core_ref, rmsf_positions=rmsf_positions
    )
    return {
        "ready": source["descriptors"] is not None,
        "stage_name": stage_name,
        "n_frames": n_frames,
        **source,
    }


# ── Trajectory-range export helpers (POST /oxdna/jobs/{id}/export-trajectory) ──
# Pure, unit-tested in tests/test_oxdna_export_trajectory.py — kept small + format-critical.


def _strided_indices(lo: int, hi: int, cap: int) -> list[int]:
    """Evenly-spaced indices from the half-open range [lo, hi), capped at ``cap``.

    Returns every index when the range fits under the cap; otherwise strides down to
    exactly ``cap`` monotonic indices that always include ``lo`` and never reach ``hi``
    (so an exported frame index is always in range). Empty when lo >= hi.
    """
    if lo >= hi:
        return []
    n = hi - lo
    if n <= cap:
        return list(range(lo, hi))
    return [lo + (i * n) // cap for i in range(cap)]


def _dat_particle_line(pos, a1, a3) -> str:
    """One oxDNA ``.dat`` configuration line: 15 floats — position, a1, a3, then zero
    velocity and angular velocity — group-separated by a double space, each ``%.6f``."""

    def _g(t):
        return " ".join(f"{v:.6f}" for v in t)

    zero = (0.0, 0.0, 0.0)
    return "  ".join([_g(pos), _g(a1), _g(a3), _g(zero), _g(zero)])


def _assemble_multiframe_pdb(
    design, model, flats, indices, export_pdb_fn, progress=None
) -> str:
    """Stamp each composite frame's atom coordinates onto ``model`` and emit a multi-MODEL PDB.

    ``flats`` maps ``str(frame_index) -> [x0,y0,z0, x1,y1,z1, …]`` (3 floats per model atom).
    For each index in ``indices`` we overwrite the model's atom xyz from its flat and render
    one PDB via ``export_pdb_fn(design, model=model, viewer_terminals=False)``, wrapping its
    ATOM/TER lines in a MODEL/ENDMDL block. Bonds are constant across frames, so the CONECT
    records are emitted ONCE (from the first surviving frame), after all models, before END.

    A frame whose flat is missing or the wrong length (topology changed) is skipped, but still
    advances ``progress(done, total)`` so a partly-invalid range's bar never stalls. Returns
    "" when no frame survives.
    """
    expect = 3 * len(model.atoms)
    total = len(indices)
    out: list[str] = []
    conect: list[str] | None = None
    model_no = 0
    for done, idx in enumerate(indices, start=1):
        flat = flats.get(str(idx))
        if flat is not None and len(flat) == expect:
            model_no += 1
            block, frame_conect = _render_model_block(
                design, model, flat, export_pdb_fn, model_no
            )
            if conect is None:
                conect = frame_conect
            out.append(block)
        if progress:
            progress(done, total)
    if not out:
        return ""
    tail = list(conect or [])
    tail.append("END")
    return "".join(out) + "\n".join(tail) + "\n"


def _render_model_block(design, model, flat, export_pdb_fn, model_no: int):
    """Stamp ONE frame's coordinates onto ``model`` and render its MODEL…ENDMDL block.

    Returns ``(block_text, conect_lines)``. The block is self-contained and newline-terminated;
    CONECT is returned separately because it is frame-invariant and belongs after the last
    model. This is the authoritative (slow) renderer — one full ``export_pdb`` per frame — and
    it is what ``pdb_export.build_multiframe_pdb_template`` is validated against.
    """
    for i, atom in enumerate(model.atoms):
        atom.x, atom.y, atom.z = flat[3 * i], flat[3 * i + 1], flat[3 * i + 2]
    pdb = export_pdb_fn(design, model=model, viewer_terminals=False)
    lines = pdb.splitlines()
    body = [ln for ln in lines if ln.startswith(("ATOM", "HETATM", "ANISOU", "TER"))]
    conect = [ln for ln in lines if ln.startswith("CONECT")]
    block = [f"MODEL     {model_no:>4d}", *body, "ENDMDL"]
    return "\n".join(block) + "\n", conect


def _export_stem(job, design) -> str:
    """A safe filename stem: the design name with non-alphanumerics replaced by ``_``,
    falling back to the job id when there is no name."""
    import re

    name = getattr(getattr(design, "metadata", None), "name", None)
    if name:
        return re.sub(r"[^A-Za-z0-9]", "_", name)
    return getattr(job, "job_id", "export")


# Frame budget for the SPARSE (whole-lineage) trajectory view — the whole chain is strided
# down to this many frames so a long lineage stays quick to build and small to ship.  The
# FULL view (scope='job') bypasses it entirely; see get_oxdna_trajectory.
_SPARSE_FRAME_CAP = 200


@router.get("/oxdna/jobs/{job_id}/trajectory")
async def get_oxdna_trajectory(
    job_id: str, request: Request, align: bool = True, scope: str = "lineage"
) -> dict:
    """Composite scrub-able trajectory for the WHOLE lineage: every stage of the
    selected job AND all of its ancestors (relax → field1 → field2 → …), each
    frame PBC-unwrapped + Kabsch-aligned to the design reference, downsampled,
    with a labelled tick at every stage/run boundary.  A field/production child is
    seeded from its parent's end state, so the ancestor chain plays as one
    continuous trajectory.  Feeds the View-trajectory play/pause + slider.

    ``scope='lineage'`` (default) is the SPARSE view: the whole ancestor chain strided
    down to ``_SPARSE_FRAME_CAP`` frames — quick to build and to ship.  ``scope='job'``
    is the FULL view: only THIS job's own stages, but EVERY frame oxDNA wrote, no stride.
    The full view's size scales with the run's steps-per-frame setting and can be very
    large, so the UI labels it "(slow)" and the caller opts in explicitly.
    """
    from backend.core.oxdna_health import composite_trajectory

    job = _load_job(job_id)
    design, stages, ref = _composite_inputs(job, scope)
    if not stages:
        return {"ready": False, "reason": "no trajectory yet"}
    # <= 0 disables the stride entirely — see _aligned_downsampled_frames._keep_for.
    budget = 0 if scope == "job" else _SPARSE_FRAME_CAP

    cancelled = threading.Event()

    class _TrajectoryCancelled(Exception):
        pass

    def _prog(done: int, total: int) -> None:
        if cancelled.is_set():
            raise _TrajectoryCancelled()
        _TRAJ_PROGRESS[job_id] = {"done": done, "total": total}

    _TRAJ_PROGRESS[job_id] = {"done": 0, "total": 0}
    try:
        task = asyncio.create_task(
            run_in_threadpool(
                composite_trajectory,
                design,
                stages,
                ref,
                budget,
                _prog,
                align,
                _capture_bead_count(job),
                _capture_strand_length(job),
            )
        )
        while not task.done():
            if await request.is_disconnected():
                cancelled.set()
                break
            await asyncio.sleep(0.1)
        try:
            result = await task
        except _TrajectoryCancelled:
            return {
                "ready": False,
                "reason": "cancelled",
                "n_frames": 0,
                "keys": [],
                "frames": [],
                "markers": [],
                "stages": [],
            }
    finally:
        cancelled.set()
        _TRAJ_PROGRESS.pop(job_id, None)
    return {"ready": result["n_frames"] > 0, **result}


@router.get("/oxdna/jobs/{job_id}/trajectory-progress")
async def get_oxdna_trajectory_progress(job_id: str) -> dict:
    """Live frames-processed progress for an in-flight composite-trajectory build.
    The View-trajectory UI polls this while the (threadpool) build runs so a large
    structure's multi-second load shows an accurate bar instead of a dead spinner.
    ``{active:false}`` once the build has finished (or never started)."""
    p = _TRAJ_PROGRESS.get(job_id)
    if not p:
        return {"active": False}
    return {"active": True, **p}


@router.get("/oxdna/jobs/{job_id}/occupancy")
async def get_oxdna_occupancy(
    job_id: str,
    request: Request,
    align: bool = True,
    scope: str = "lineage",
    max_frames: int = _SPARSE_FRAME_CAP,
    n_clusters: int = 0,
    method: str = "pca",
    basis: str = "nt",
    refetch: bool = False,
) -> dict:
    """The top-N most likely CONFIGURATIONS of this job's sampling ensemble.

    Where ``/rmsf`` gives one mean structure plus a per-nucleotide spread, this gives
    several REAL frames — the medoid of each conformational cluster — with a population
    weight apiece.  A plate that flips between the two saddle senses of a hyperbolic
    paraboloid has a FLAT mean, a shape it never occupies; this route returns both senses
    instead.  See :mod:`backend.core.oxdna_occupancy` for the algorithm and its three
    invariants.

    The defaults deliberately match what ``/trajectory`` passes
    (``scope='lineage'``, ``max_frames=_SPARSE_FRAME_CAP``, ``copies=True``) so both
    routes hit the SAME ``_ALIGNED_CACHE`` entry — after a trajectory scrub the frames are
    already unwrapped and aligned, and occupancy costs only the linear algebra.  Changing
    ``max_frames`` is therefore not free: it re-reads the trajectory.

    ``n_clusters=0`` selects k automatically.  Read ``verdict`` before believing anything
    else in the payload:

    * ``"switching"`` — separated states that the run REVISITS. Populations are meaningful
      (check ``confidence.preliminary`` for whether they are converged).
    * ``"drift"`` — separated, but each state is entered at most once. The clusters are
      "early" and "late" in a one-way path, not configurations in equilibrium. Do not
      present them as likelihoods.
    * ``"unimodal"`` — one basin. The flexibility map already describes this ensemble.
    """
    return await _occupancy_impl(
        job_id,
        request,
        align=align,
        scope=scope,
        max_frames=max_frames,
        n_clusters=n_clusters,
        method=method,
        basis=basis,
        refetch=refetch,
    )


async def _occupancy_impl(
    job_id: str,
    request: Request,
    *,
    align: bool,
    scope: str,
    max_frames: int,
    n_clusters: int,
    method: str,
    basis: str,
    refetch: bool,
    selection=None,
    fit: str = "selection",
) -> dict:
    """Shared body for the GET (whole structure) and POST (scoped) occupancy routes."""
    from backend.core.occupancy_core import OCC_FIT_MODES
    from backend.core.oxdna_occupancy import production_occupancy_cached

    if method != "pca":
        raise HTTPException(400, "method must be 'pca'")
    if basis not in ("nt", "bp"):
        raise HTTPException(400, "basis must be 'nt' or 'bp'")
    if fit not in OCC_FIT_MODES:
        raise HTTPException(400, f"fit must be one of {', '.join(OCC_FIT_MODES)}")
    n_clusters = int(max(0, min(6, n_clusters)))
    max_frames = int(max(0, max_frames))

    job = _load_job(job_id)
    design, stages, ref = _composite_inputs(job, scope)
    if not stages:
        return {"ready": False, "reason": "no production or field run yet"}

    cancelled = threading.Event()

    class _OccupancyCancelled(Exception):
        pass

    def _prog(done: int, total: int) -> None:
        if cancelled.is_set():
            raise _OccupancyCancelled()
        _OCC_PROGRESS[job_id] = {"done": done, "total": total}

    _OCC_PROGRESS[job_id] = {"done": 0, "total": 0}
    try:
        task = asyncio.create_task(
            run_in_threadpool(
                lambda: production_occupancy_cached(
                    design,
                    stages,
                    ref,
                    max_frames=max_frames,
                    n_clusters=n_clusters,
                    method=method,
                    basis=basis,
                    align=align,
                    progress=_prog,
                    refetch=refetch,
                    selection=selection,
                    fit=fit,
                    n_trailing_extra=_capture_bead_count(job),
                    trailing_extra_strand_length=_capture_strand_length(job),
                )
            )
        )
        while not task.done():
            if await request.is_disconnected():
                cancelled.set()
                break
            await asyncio.sleep(0.1)
        try:
            result = await task
        except _OccupancyCancelled:
            return {"ready": False, "reason": "cancelled", "clusters": [], "keys": []}
    finally:
        cancelled.set()
        _OCC_PROGRESS.pop(job_id, None)

    prod_running = any(
        s.status == "running" for s in job.stages if s.kind in ("production", "field")
    )
    return {**result, "production_running": prod_running}


class OccupancySelection(BaseModel):
    """Which part of the structure the clustering may look at.

    A union of criteria — a nucleotide is in scope if it matches ANY of them.
    Everything empty means the whole structure, which is the same analysis the GET does.

    ``extra="forbid"``, so a criterion the model does not declare is a 422 rather than a
    silent no-scope. Any new criterion must also be added to
    ``oxdna_occupancy._selection_sig`` or two different scopes collide in the cache.
    """

    model_config = ConfigDict(extra="forbid")
    cluster_ids: list[str] = Field(default_factory=list)
    helix_ids: list[str] = Field(default_factory=list)
    strand_ids: list[str] = Field(default_factory=list)
    overhang_ids: list[str] = Field(default_factory=list)
    domains: list[list] = Field(default_factory=list)  # [strand_id, domain_index]
    bases: list[list] = Field(default_factory=list)  # [helix_id, bp_index, direction]
    # Synthetic beads — omit the trailing index to take the whole run/tail.
    extra_bases: list[list] = Field(default_factory=list)  # [crossover_id, k?]
    extensions: list[list] = Field(default_factory=list)  # [extension_id, k?]


class OccupancyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    align: bool = True
    scope: str = "lineage"
    max_frames: int = _SPARSE_FRAME_CAP
    n_clusters: int = 0
    method: str = "pca"
    basis: str = "nt"
    refetch: bool = False
    selection: Optional[OccupancySelection] = None
    #: Reference frame for a SCOPED run — "selection" | "local" | "global". Ignored when
    #: there is no selection (an unscoped run is always the whole-structure fit).
    fit: str = "selection"


@router.post("/oxdna/jobs/{job_id}/occupancy")
async def post_oxdna_occupancy(
    job_id: str, request: Request, body: OccupancyBody
) -> dict:
    """Occupancy clouds restricted to PART of the structure.

    Same analysis as the GET, plus a `selection` of clusters / strands / domains /
    overhangs / individual bases / crossover extra bases / extension tails. Scoping matters
    because a global clustering is dominated by the largest-amplitude motion in the whole
    object; a local hinge or a single flexible seam that flips between two well-defined
    states can sit entirely inside the noise floor of that fit. Restricting the feature
    matrix is what makes those local states visible.

    The scoped run is then RE-SUPERPOSED, because the frames arrive fitted on the whole
    structure and a sub-region still carries its rigid-body motion inside that fit — PCA
    would cluster on where the region was rather than what shape it took. ``fit`` picks the
    frame: ``"selection"`` (default, fit on the picked points — duplex-paired ones only
    when the pick is mixed), ``"local"`` (each crossover extra base on its own junction's
    flanking duplex), or ``"global"`` (the old behaviour, keep the whole-structure fit).
    The response reports ``fit``/``fit_requested``/``fit_note``: a mode degrades rather
    than lying, exactly as ``basis`` does.

    POST rather than GET because a base-level selection is far too big for a query string.
    """
    return await _occupancy_impl(
        job_id,
        request,
        align=body.align,
        scope=body.scope,
        max_frames=body.max_frames,
        n_clusters=body.n_clusters,
        method=body.method,
        basis=body.basis,
        refetch=body.refetch,
        fit=body.fit,
        selection=body.selection.model_dump() if body.selection else None,
    )


@router.get("/oxdna/jobs/{job_id}/occupancy-progress")
async def get_oxdna_occupancy_progress(job_id: str) -> dict:
    """Live frames-processed progress for an in-flight occupancy build.

    Deliberately a SEPARATE dict from ``_TRAJ_PROGRESS``: a trajectory build and an
    occupancy build for the same job would otherwise overwrite each other's bar."""
    p = _OCC_PROGRESS.get(job_id)
    if not p:
        return {"active": False}
    return {"active": True, **p}


@router.get("/oxdna/jobs/{job_id}/trajectory-meta")
async def get_oxdna_trajectory_meta(job_id: str, scope: str = "lineage") -> dict:
    """Frame count + stage markers for the composite trajectory WITHOUT downloading
    coordinates — lets the trajectory-keyframe slider size itself instantly. Indices
    match GET /oxdna/jobs/{id}/trajectory exactly, ``scope`` included — pass the SAME
    scope both places or the slider will size to a different frame count than the
    payload it scrubs."""
    from backend.core.oxdna_health import composite_trajectory_meta

    job = _load_job(job_id)
    design, stages, _ = _composite_inputs(job, scope)
    if not stages:
        return {"ready": False, "reason": "no trajectory yet"}
    budget = 0 if scope == "job" else _SPARSE_FRAME_CAP
    result = await run_in_threadpool(composite_trajectory_meta, design, stages, budget)
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
async def oxdna_frames_atomistic(
    job_id: str,
    body: OxdnaFramesAtomisticBody,
    align: bool = True,
    scope: str = "lineage",
) -> dict:
    """Per-frame ATOMISTIC coordinates for the given composite-trajectory frame
    indices (same wire format as /design/features/atomistic-batch). Used by the
    animation player to make the atomistic rep follow a trajectory keyframe.
    Heavy — one full all-atom rebuild per frame — so callers pass a downsampled
    index set. Indices match GET /oxdna/jobs/{id}/trajectory frame ordering — pass the
    SAME ``scope`` the trajectory was loaded with, or the indices address other frames."""
    from backend.core.oxdna_health import composite_trajectory_atomistic

    job = _load_job(job_id)
    design, stages, ref = _composite_inputs(job, scope)
    if not stages:
        return {}
    return await run_in_threadpool(
        composite_trajectory_atomistic,
        design,
        stages,
        ref,
        body.frame_indices,
        max_frames=(0 if scope == "job" else _SPARSE_FRAME_CAP),
        align=align,
        n_trailing_extra=_capture_bead_count(job),
        trailing_extra_strand_length=_capture_strand_length(job),
    )


@router.post("/oxdna/jobs/{job_id}/frames-surface")
async def oxdna_frames_surface(
    job_id: str,
    body: OxdnaFramesSurfaceBody,
    align: bool = True,
    scope: str = "lineage",
) -> dict:
    """Per-frame molecular SURFACE meshes for the given composite-trajectory frame
    indices (same wire format as /design/features/surface-batch). Heaviest path
    (all-atom rebuild + marching cubes per frame) — callers downsample hard. Pass the
    SAME ``scope`` the trajectory was loaded with so the indices address the same frames."""
    from backend.core.oxdna_health import composite_trajectory_surface

    job = _load_job(job_id)
    design, stages, ref = _composite_inputs(job, scope)
    if not stages:
        return {}
    return await run_in_threadpool(
        composite_trajectory_surface,
        design,
        stages,
        ref,
        body.frame_indices,
        body.color_mode,
        body.probe_radius,
        body.grid_spacing,
        body.radius_inflate,
        body.smooth,
        max_frames=(0 if scope == "job" else _SPARSE_FRAME_CAP),
        align=align,
        n_trailing_extra=_capture_bead_count(job),
        trailing_extra_strand_length=_capture_strand_length(job),
    )


class OxdnaExportTrajectoryBody(BaseModel):
    lo: int
    hi: int
    format: str = "pdb"  # 'pdb' (multi-MODEL, ChimeraX) | 'oxdna' (.top+.dat, oxView)


# Each exported frame is a full all-atom rebuild, so cap the count regardless of the range —
# the SPARSE composite frame space is already downsampled (≤_SPARSE_FRAME_CAP), so this only
# bites a huge request there.  It is the real limit for a full-scope (unstrided) trajectory.
_EXPORT_FRAME_CAP = 240


async def _export_dcd_bundle(job_id: str, job, design, stages, ref, indices, stem: str):
    """Export a frame range as a ChimeraX-ready **topology PDB + binary DCD** pair, zipped.

    Why this beats the multi-MODEL PDB: coordinates are 12 binary bytes per atom per frame
    instead of ~80 ASCII, and the topology (atom names, chains, CONECT) is serialised ONCE
    rather than re-emitted every frame. For a 51-frame, 330k-atom range that is ~1.35 GB of
    text down to ~200 MB — and the per-frame text formatting disappears entirely.

    Both files are written to a temp dir a frame at a time, so peak memory is one frame no
    matter how long the trajectory is; the zip is then streamed from disk and the temp dir
    removed in a background task once the response completes.
    """
    import shutil
    import tempfile
    import zipfile

    import numpy as np
    from starlette.background import BackgroundTask

    from backend.core import dcd_fast
    from backend.core.atomistic import build_atomistic_model
    from backend.core.oxdna_health import iter_composite_trajectory_atomistic
    from backend.core.pdb_export import export_pdb

    def _frame_prog(done: int, total: int) -> None:
        _EXPORT_PROGRESS[job_id] = {"done": done, "total": total, "phase": "frames"}

    tmpdir = tempfile.mkdtemp(prefix="nadoc_export_")

    def _build() -> tuple[str, int]:
        model = build_atomistic_model(design)
        expect = 3 * len(model.atoms)
        frames = iter_composite_trajectory_atomistic(
            design,
            stages,
            ref,
            indices,
            n_trailing_extra=_capture_bead_count(job),
            trailing_extra_strand_length=_capture_strand_length(job),
            progress=_frame_prog,
            cache=False,
        )

        wrote_topology = False
        n_written = 0

        def _coords():
            """Yield each frame as (n_atoms, 3) Angstroms, writing the topology PDB from
            the first surviving frame so the two files describe the same coordinates."""
            nonlocal wrote_topology, n_written
            for _idx, flat in frames:
                if len(flat) != expect:
                    continue  # topology changed mid-range; skip, as the PDB path does
                arr = np.asarray(flat, dtype=np.float64).reshape(-1, 3)
                if not wrote_topology:
                    for i, atom in enumerate(model.atoms):
                        atom.x, atom.y, atom.z = arr[i, 0], arr[i, 1], arr[i, 2]
                    (Path(tmpdir) / f"{stem}.pdb").write_text(
                        export_pdb(design, model=model, viewer_terminals=False)
                    )
                    wrote_topology = True
                n_written += 1
                yield arr * 10.0  # nm -> Angstrom (DCD's unit)

        dcd_fast.write_trajectory(
            Path(tmpdir) / f"{stem}.dcd", len(model.atoms), _coords(), len(indices)
        )
        if not wrote_topology:
            return "", 0

        zip_path = Path(tmpdir) / f"{stem}.zip"
        with zipfile.ZipFile(
            zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1
        ) as zf:
            zf.write(Path(tmpdir) / f"{stem}.pdb", f"{stem}.pdb")
            zf.write(Path(tmpdir) / f"{stem}.dcd", f"{stem}.dcd")
            zf.writestr(
                f"{stem}_README.txt",
                "Open in ChimeraX:\n"
                f"    open {stem}.pdb\n"
                f"    open {stem}.dcd structureModel #1\n\n"
                "The PDB carries the topology (one frame); the DCD carries every\n"
                "frame's coordinates. Both files must be in the same folder.\n",
            )
        return str(zip_path), n_written

    try:
        zip_path, n_written = await run_in_threadpool(_build)
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    finally:
        _EXPORT_PROGRESS.pop(job_id, None)

    if not zip_path:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(
            500,
            "No frames could be rendered — this can happen for hard-surface / capture-strand "
            "jobs whose extra beads aren't in the atomistic model.",
        )

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"{stem}_chimerax.zip",
        background=BackgroundTask(shutil.rmtree, tmpdir, True),
    )


@router.post("/oxdna/jobs/{job_id}/export-trajectory")
async def export_oxdna_trajectory(
    job_id: str, body: OxdnaExportTrajectoryBody
) -> Response:
    """Export a FRAME RANGE of the composite trajectory for offline rendering.

    ``format='pdb'`` → one multi-MODEL PDB (ChimeraX ``open … coordsets true``); the frame
    indices match GET /oxdna/jobs/{id}/trajectory exactly, so the range the export card's slider
    shows is the range emitted. Heavy (one all-atom rebuild per frame) — progress streams to
    ``/export-progress``. ``format='oxdna'`` (oxView .top+.dat) is not wired yet.
    """
    from backend.core.oxdna_health import composite_trajectory_meta

    if body.format not in ("pdb", "dcd", "oxdna"):
        raise HTTPException(400, f"Unknown export format {body.format!r}.")
    job = _load_job(job_id)
    design, stages, ref = _composite_inputs(job)
    if not stages:
        raise HTTPException(
            404, "This job has no trajectory to export yet — run a production job."
        )

    meta = await run_in_threadpool(composite_trajectory_meta, design, stages)
    n_frames = int(meta.get("n_frames") or 0)
    lo = max(0, min(int(body.lo), n_frames))
    hi = max(0, min(int(body.hi), n_frames))
    indices = _strided_indices(lo, hi, _EXPORT_FRAME_CAP)
    if not indices:
        raise HTTPException(400, "The selected frame range is empty.")

    if body.format == "oxdna":
        # A faithful multi-frame oxDNA .dat needs each particle's a1 AND a3 versors in TOPOLOGY
        # order; the composite frames carry pos+a1 in a different key order, so the .top/.dat
        # correspondence isn't wired yet. PDB is the supported path (ChimeraX).
        raise HTTPException(
            501,
            "oxView (.top + .dat) trajectory export isn't wired yet — export as a "
            "multi-frame PDB (the PDB option) for ChimeraX for now.",
        )

    from backend.core.atomistic import build_atomistic_model
    from backend.core.oxdna_health import iter_composite_trajectory_atomistic
    from backend.core.pdb_export import build_multiframe_pdb_template, export_pdb

    stem = _export_stem(job, design)
    filename = f"{stem}_frames{lo}-{hi}.pdb"
    _EXPORT_PROGRESS[job_id] = {"done": 0, "total": len(indices), "phase": "align"}

    if body.format == "dcd":
        return await _export_dcd_bundle(
            job_id, job, design, stages, ref, indices, f"{stem}_frames{lo}-{hi}"
        )

    def _frame_prog(done: int, total: int) -> None:
        # One counting phase now: each frame is rebuilt AND written before the next starts.
        _EXPORT_PROGRESS[job_id] = {"done": done, "total": total, "phase": "frames"}

    # ── Prepare BEFORE the response starts ────────────────────────────────────
    # Streaming means the status line is committed with the first byte, so anything that
    # should surface as a clean HTTP error (no renderable frames) has to be discovered
    # here, not mid-stream where the only failure mode is a truncated download.
    def _prepare():
        model = build_atomistic_model(design)
        template = build_multiframe_pdb_template(design, model)
        frames = iter_composite_trajectory_atomistic(
            design,
            stages,
            ref,
            indices,
            n_trailing_extra=_capture_bead_count(job),
            trailing_extra_strand_length=_capture_strand_length(job),
            progress=_frame_prog,
            # An export's frames are write-once; caching them would evict the live
            # display cache (6 M-element budget) for entries nobody re-requests.
            cache=False,
        )
        expect = 3 * len(model.atoms)
        first = None
        for _idx, flat in frames:
            if len(flat) == expect:
                first = flat
                break
        if first is None:
            return model, None, frames, None, None, None
        # Prove the splice against the authoritative renderer on REAL frame data before
        # trusting it for the remaining frames. build_multiframe_pdb_template assumes the
        # k-th ATOM line belongs to model.atoms[k]; if export_pdb ever reorders or filters,
        # a silent splice would corrupt every exported coordinate. One extra render is cheap
        # next to that failure mode — and it doubles as frame 1's own reference rendering.
        first_block, conect = _render_model_block(design, model, first, export_pdb, 1)
        if template is not None and template.model_block(first, 1) != first_block:
            template = None
        return model, template, frames, first, first_block, conect

    try:
        model, template, frames, first, first_block, conect = await run_in_threadpool(
            _prepare
        )
    except Exception:
        _EXPORT_PROGRESS.pop(job_id, None)
        raise

    if first is None:
        # Every frame's atom count mismatched the model — happens on capture/surface jobs whose
        # trailing beads aren't in the base atomistic model. Fail with a clear reason.
        _EXPORT_PROGRESS.pop(job_id, None)
        raise HTTPException(
            500,
            "No frames could be rendered — this can happen for hard-surface / capture-strand "
            "jobs whose extra beads aren't in the atomistic model.",
        )

    expect = 3 * len(model.atoms)

    def _stream():
        """Emit MODEL blocks as they are built. Peak memory is ONE frame instead of the whole
        range, and the browser starts saving immediately rather than after the last frame.

        Byte-for-byte the same document the non-streaming builder produced: MODEL blocks, then
        the single frame-invariant CONECT block, then END. No REMARK/CRYST1 preamble — the
        multi-frame format never carried one.
        """
        try:
            yield first_block
            model_no = 1
            for _idx, flat in frames:
                if len(flat) != expect:
                    continue  # topology changed mid-range; skip it
                model_no += 1
                if template is not None:
                    yield template.model_block(flat, model_no)
                else:
                    # Defensive fallback: the splice couldn't be validated, so pay the full
                    # per-frame render. Correct, just slow — never silently wrong.
                    block, _ = _render_model_block(
                        design, model, flat, export_pdb, model_no
                    )
                    yield block
            tail = list(conect or [])
            tail.append("END")
            yield "\n".join(tail) + "\n"
        finally:
            _EXPORT_PROGRESS.pop(job_id, None)

    return StreamingResponse(
        _stream(),
        media_type="chemical/x-pdb",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/oxdna/jobs/{job_id}/export-progress")
async def get_oxdna_export_progress(job_id: str) -> dict:
    """Live frames-processed progress for an in-flight trajectory-range export build.
    ``{active:false}`` when nothing is exporting. Polled by the export card's progress bar."""
    p = _EXPORT_PROGRESS.get(job_id)
    if not p:
        return {"active": False}
    return {"active": True, **p}


def _job_has_surface(job) -> bool:
    """Whether the job was run against a hard surface (relax surface, capture strands, or a
    field/run child that inherited/added one).  Alignment is disallowed for these."""
    rc = job.run_config or {}
    return bool(rc.get("surface") or rc.get("surface_strands"))


def _capture_bead_count(job) -> int:
    """Number of non-design capture particles appended to every oxDNA frame."""
    from backend.physics.oxdna_surface_strands import capture_bead_count

    return capture_bead_count(job)


def _capture_strand_length(job) -> int:
    sequence = ((job.run_config or {}).get("surface_strands") or {}).get(
        "sequence"
    ) or ""
    return len("".join(base for base in sequence.upper() if base in "ACGT"))


def _relaxed_full_map(
    job,
    align: bool,
    *,
    copies: bool = False,
    include_extra_bases: bool = False,
    include_extensions: bool = False,
):
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
    simulated positions instead of the geometric arc.  ``include_extensions=True``
    does the same for strand-extension tail beads (keyed ``("__ext_<id>", i, dir)``)."""
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

    # Alignment is DISALLOWED for surface jobs: Kabsch-superposing the relaxed structure back
    # onto the design origin undoes the settling that keeps it above the plane, so it renders
    # as if clipping through the surface.  Forcing it off also spares aligning the extra
    # capture-strand beads.  (The PBC unwrap + box-shift to the reference still run, so the
    # structure stays whole and near the plane — only the misleading superpose is dropped.)
    if _job_has_surface(job):
        align = False

    from backend.core.models import Design

    snap = jd / "design.json"
    if not snap.exists():
        raise HTTPException(500, "design.json snapshot missing for this job")
    design = Design.model_validate_json(snap.read_text())

    # A job written by an older build can have FEWER particles than the design now
    # walks to (strand extensions add one per extension base).  The reader cannot
    # detect that on its own — it clamps the deficit and silently hands every
    # nucleotide after the first extension the WRONG particle line.  Fail loudly.
    from backend.physics.oxdna_interface import (
        assert_topology_matches_design,
        StaleJobTopologyError,
    )

    # Surface capture strands are appended after the origami particles — a legitimate,
    # job-specific surplus that isn't in the design walk.  Allow it in the guard and skip
    # it in the reader so the origami particles still line up.
    cap_beads = _capture_bead_count(job)
    try:
        assert_topology_matches_design(
            jd / "topology.top", design, extra_trailing=cap_beads
        )
    except StaleJobTopologyError as exc:
        raise HTTPException(409, str(exc)) from exc

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
        # An anchor on a SYNTHETIC bead (crossover extra base / extension tail) can only
        # act as the alignment reference if that bead is in the map at all. The default
        # here is include_*=False, so without this the align subset comes back empty,
        # `unwrap_align_to_reference` falls through to T = zeros(3), and the structure
        # renders UNALIGNED with no error — the exact silent failure that makes an anchor
        # look like it did nothing.
        _keys = [tuple(k) for k in anchor_keys]
        _extra_b = include_extra_bases or any(k and k[0] == _XB_SENTINEL for k in _keys)
        _exts = include_extensions or any(is_extension_key(k) for k in _keys if k)
        full_map = read_configuration_unwrapped(
            conf_path,
            design,
            ref_conf,
            align_keys=_keys,
            rotate=False,
            align=align,
            copies=copies,
            include_extra_bases=_extra_b,
            include_extensions=_exts,
            n_trailing_extra=cap_beads,
        )
    else:
        full_map = read_configuration_unwrapped(
            conf_path,
            design,
            ref_conf,
            align=align,
            copies=copies,
            include_extra_bases=include_extra_bases,
            include_extensions=include_extensions,
            n_trailing_extra=cap_beads,
        )
    return (design, full_map, stage_name, conf_path, ref_conf)


def _capture_display_strands(job, conf_path, full_map) -> list:
    """Real relaxed capture-strand bead positions (nm), grouped per strand, for the display.

    Capture beads are the trailing particles [N_orig..N_total) — NOT design nucleotides, so
    they ride a separate render channel.  Alignment is forced off for surface jobs, so the
    frame is the raw simulation frame (how it settled on the surface); the only correction is
    a single box-shift of the whole capture group onto the origami's display box-image.
    Returns [] for non-capture jobs."""
    import numpy as np

    ss = (job.run_config or {}).get("surface_strands") or {}
    built = ss.get("built") or {}
    n_cap = int(built.get("n_beads", 0))
    if n_cap <= 0 or not full_map:
        return []
    seq = "".join(c for c in (ss.get("sequence") or "").upper() if c in "ACGT")
    L = len(seq) or 8
    from backend.physics.oxdna_interface import OXDNA_LENGTH_UNIT, _parse_box_nm

    lines = [
        l
        for l in Path(conf_path).read_text().splitlines()
        if l.strip() and not l.startswith(("t ", "b ", "E "))
    ]
    n_orig = len(lines) - n_cap
    if n_orig < 0 or n_cap % L != 0:
        return []
    cap = (
        np.array(
            [[float(x) for x in lines[n_orig + i].split()[:3]] for i in range(n_cap)]
        )
        * OXDNA_LENGTH_UNIT
    )
    box = _parse_box_nm(conf_path)
    origami_c = np.mean([v["backbone_position"] for v in full_map.values()], axis=0)
    if box is not None and np.all(box > 0):
        cap = cap + box * np.round((origami_c - cap.mean(axis=0)) / box)
    return [cap[s * L : (s + 1) * L].tolist() for s in range(n_cap // L)]


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
    # copies=True keys each loop-insertion copy under its own 4-tuple so the display
    # can move every loop bead (not just the collapsed last copy) to its relaxed spot.
    design, full_map, stage_name, conf_path, ref_conf = _relaxed_full_map(
        job, align, copies=True, include_extra_bases=True, include_extensions=True
    )
    if full_map is None:
        return {
            "job_id": job.job_id,
            "ready": False,
            "positions": [],
            "stage_name": None,
        }

    # Hybrid (protein) jobs: a per-protein rigid 4×4 (design pose → relaxed pose in
    # the aligned display frame) the frontend applies to the protein render.
    proteins = []
    from backend.physics.oxdna_protein import has_proteins, protein_display_transforms

    if has_proteins(design):
        transforms = protein_display_transforms(
            conf_path, ref_conf, design, _seed_geometry(design), align=align
        )
        proteins = [
            {"attachment_id": aid, "transform": M} for aid, M in transforms.items()
        ]
    # Render the true backbone site, not the oxDNA centre of mass — the CM sits
    # inward of the backbone, so rendering it collapses the apparent duplex.
    positions = [
        {
            "helix_id": key[0],
            "bp_index": key[1],
            "direction": key[2],
            # Loop-copy index (4-tuple key); 0 for plain nucleotides and __xb__ inserts
            # (3-tuple) so the frontend addresses the exact loop bead.
            "copy": key[3] if len(key) == 4 else 0,
            "backbone_position": oxdna_backbone_site(
                v["backbone_position"], v["a1"], v["a3"]
            ).tolist(),
            "nx": float(v["a1"][0]),
            "ny": float(v["a1"][1]),
            "nz": float(v["a1"][2]),
        }
        for key, v in full_map.items()
    ]
    return {
        "job_id": job.job_id,
        "ready": True,
        "status": job.status.value,
        "stage_name": stage_name,
        "n_positions": len(positions),
        "positions": positions,
        "proteins": proteins,
        # Real relaxed surface capture strands (per-strand bead position lists, nm) — a
        # separate render channel; [] for non-capture jobs.
        "surface_strands": _capture_display_strands(job, conf_path, full_map),
    }


class OxdnaSurfaceBody(BaseModel):
    color_mode: str = "strand"
    probe_radius: float = 0.28
    grid_spacing: float = 0.20
    radius_inflate: float = 1.30
    smooth: int = 15
    detail: str = (
        "coarse"  # 'coarse' = fast CG-bead envelope (default) | 'fine' = full all-atom
    )


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
    from backend.core.oxdna_health import (
        frame_atomistic_flat,
        _traj_file_sig,
        _display_out_get,
        _display_out_put,
    )
    from backend.core.atomistic import atomistic_reference_topology_hash

    job = _load_job(job_id)
    design, full_map, stage_name, conf_path, _ = _relaxed_full_map(
        job, align, copies=True, include_extra_bases=True, include_extensions=True
    )
    if full_map is None:
        return {"job_id": job.job_id, "ready": False}
    # Cache the all-atom rebuild (the "≈ several seconds" step) keyed by the conf
    # file's signature + align, so flipping the representation atomistic→surface→
    # atomistic on the same relaxed frame re-fetches instantly.  The signature
    # changes when a still-writing run advances the conf, so a live run stays fresh.
    ck = ("dispA", _traj_file_sig(str(conf_path)), bool(align))
    data = _display_out_get(ck)
    if data is None:
        data = await run_in_threadpool(frame_atomistic_flat, design, full_map)
        _display_out_put(ck, data)
    return {
        "job_id": job.job_id,
        "ready": True,
        "stage_name": stage_name,
        "atomistic": data,
        "topology_hash": atomistic_reference_topology_hash(design),
        "n_atoms": len(data) // 3,
    }


@router.get("/oxdna/jobs/{job_id}/atomistic-model")
async def get_oxdna_atomistic_model(job_id: str) -> dict:
    """The JOB design's full atomistic model (atoms + bonds, in design positions) so
    the frontend can REBUILD the renderer from the topology the relaxed positions
    belong to — when the app's loaded design has diverged from the job snapshot.
    Same serial space as display-atomistic's flat positions (both build from the job
    design), so a rebuild + applyPositionLerp aligns bond-for-bond."""
    from backend.core.atomistic import (
        build_atomistic_model,
        atomistic_to_json,
        atomistic_reference_topology_hash,
    )
    from backend.core.models import Design

    job = _load_job(job_id)
    snap = job.job_dir(_workspace()) / "design.json"
    if not snap.exists():
        raise HTTPException(500, "design.json snapshot missing for this job")
    design = Design.model_validate_json(snap.read_text())
    # Display topology only — the relaxed positions overwrite these coords via
    # applyPositionLerp, so use the cheap interpolated phosphate bridges (6× faster
    # build on large structures; the exact MD-seed geometry would be discarded anyway).
    model = await run_in_threadpool(
        lambda: build_atomistic_model(design, fast_bridges=True)
    )
    out = atomistic_to_json(model)
    out["topology_hash"] = atomistic_reference_topology_hash(design)
    return out


@router.get("/oxdna/jobs/{job_id}/atomistic-stamp")
async def get_oxdna_atomistic_stamp(job_id: str) -> dict:
    """Design-FIXED stamp descriptor for the fast CG→atomistic display path — fetched
    ONCE per job alongside GET .../atomistic-model.  Says, per atom serial, whether it
    is a rigid template stamp (and which nucleotide + its template-local coord) or a
    non-rigid atom (closure/bridge/insert/tail).  The per-frame POST
    .../display-atomistic-frames then ships only per-nucleotide frames + the non-rigid
    positions, and the client expands ``origin + R @ local`` for the rigid majority.

    Same serial space + ``topology_hash`` as atomistic-model (both build from the JOB
    design), so the client rebuilds from atomistic-model on a hash mismatch."""
    from backend.core.atomistic import atomistic_stamp_descriptor
    from backend.core.models import Design

    job = _load_job(job_id)
    snap = job.job_dir(_workspace()) / "design.json"
    if not snap.exists():
        raise HTTPException(500, "design.json snapshot missing for this job")
    design = Design.model_validate_json(snap.read_text())
    desc = await run_in_threadpool(atomistic_stamp_descriptor, design)
    # Flatten atom_local (3*n_atoms) for a compact wire; nuc_keys as [h,bp,dir,copy].
    atom_local_flat: list = []
    for nx, ny, nz in desc.atom_local:
        atom_local_flat.extend((nx, ny, nz))
    return {
        "job_id": job.job_id,
        "topology_hash": desc.topology_hash,
        "n_nuc": len(desc.nuc_keys),
        "n_atoms": len(desc.atom_nuc),
        "nuc_keys": [list(k) for k in desc.nuc_keys],
        "atom_nuc": desc.atom_nuc,
        "atom_local": atom_local_flat,
        "nonrigid_serials": desc.nonrigid_serials,
    }


def _atomistic_bundle_ctx(job_id: str):
    """(design, topology_hash, job_dir) for a job's display bundle — the bit both bundle
    routes need before they can decide whether their cache is warm."""
    from backend.core.atomistic import atomistic_reference_topology_hash
    from backend.core.models import Design

    job = _load_job(job_id)
    jd = job.job_dir(_workspace())
    snap = jd / "design.json"
    if not snap.exists():
        raise HTTPException(500, "design.json snapshot missing for this job")
    design = Design.model_validate_json(snap.read_text())
    return design, atomistic_reference_topology_hash(design), jd


def _atomistic_bin_cache_path(jd, thash: str):
    """Packed-blob cache path. The topology hash is in the FILENAME so it self-invalidates
    (no need to parse the blob to decide whether it is stale)."""
    return jd / f"atomistic_display_bundle_{thash[:16]}.bin"


def _write_atomistic_bin_cache(bundle: dict, jd, thash: str) -> None:
    """Pack + persist the binary bundle.  Best-effort: a failure here only costs the next
    request a repack, never correctness, and an unpackable bundle is a legitimate outcome
    (the bin route 409s and the client falls back to JSON)."""
    from backend.core.atomistic import pack_bundle_bin

    try:
        _atomistic_bin_cache_path(jd, thash).write_bytes(pack_bundle_bin(bundle))
    except Exception:
        pass


async def _atomistic_bundle_cached(job_id: str, ctx=None) -> dict:
    """The job's full display bundle, built once ever and held on disk (keyed by topology
    hash).  Shared by the JSON and binary routes so there is exactly ONE build path and
    one cache; the routes only differ in how they serialise the result."""
    import orjson
    from backend.core.atomistic import atomistic_display_bundle

    design, thash, jd = ctx if ctx is not None else _atomistic_bundle_ctx(job_id)
    cache_f = jd / "atomistic_display_bundle.json"

    def _read_cache():
        if cache_f.exists():
            try:
                # orjson: the cache is ~129 MB and stdlib json.loads costs ~1.4 s on it.
                cached = orjson.loads(cache_f.read_bytes())
                if cached.get("topology_hash") == thash:
                    return cached
            except Exception:
                pass  # corrupt/stale cache → rebuild
        return None

    hit = _read_cache()
    if hit is not None:
        return hit
    # Single-flight: hold the per-topology lock across the build so a second request
    # (a real click racing the warm-ahead prefetch) blocks and then takes the cached
    # result instead of launching its own build.
    lock = await _bundle_build_lock(thash)
    async with lock:
        hit = _read_cache()  # another request may have just built + cached it
        if hit is not None:
            return hit
        out = await run_in_threadpool(atomistic_display_bundle, design)

        def _persist():
            try:
                cache_f.write_bytes(orjson.dumps(out))
            except Exception:
                pass  # cache write best-effort; correctness doesn't depend on it
            # Pack the binary form NOW, off the in-memory bundle. Deriving it lazily on
            # the first bin request instead would mean re-reading and re-parsing the
            # 129 MB JSON cache just to throw it away — the build already has the dict.
            _write_atomistic_bin_cache(out, jd, thash)

        await run_in_threadpool(_persist)
        return out


@router.get("/oxdna/jobs/{job_id}/atomistic-display-bundle")
async def get_oxdna_atomistic_display_bundle(job_id: str, bonds: bool = True) -> dict:
    """Combined renderer topology (atoms+bonds) + stamp descriptor in ONE build
    (fast interpolated bridges), DISK-CACHED per job by topology hash — so the whole
    display-atomistic setup for a job is built once ever, not per switch/session.

    ``bonds=false`` omits the bond list from the RESPONSE (the disk cache always holds
    the full bundle).  The VDW rep draws no cylinders, so shipping ~370k bond pairs to
    it is pure wire + JSON.parse cost; the client asks for them back when it needs
    ball-and-stick.

    LEGACY/FALLBACK: prefer ``atomistic-display-bundle-bin`` — this JSON form is ~7×
    larger and costs the client 330k object allocations out of ``JSON.parse``."""
    bundle = await _atomistic_bundle_cached(job_id)
    if bonds:
        return bundle
    # Shallow-copy so neither the freshly parsed cache dict nor the just-built bundle
    # is mutated for other callers.
    return {k: v for k, v in bundle.items() if k != "bonds"}


@router.get("/oxdna/jobs/{job_id}/atomistic-display-bundle-bin")
async def get_oxdna_atomistic_display_bundle_bin(job_id: str):
    """Binary counterpart of atomistic-display-bundle: the SAME cached bundle packed
    columnar (typed-array columns + interned string tables for the five string fields,
    and the seven fields no frontend code reads dropped entirely).

    ~124 MB → ~18 MB on a VoltronCore-size design, and — the point — the client builds
    typed-array views instead of 330k JavaScript objects.  See
    frontend/src/scene/atomistic_bundle_bin.js for the layout.

    409 when the bundle violates a format invariant (non-dense serials, an interned
    field wider than its index type); the client falls back to the JSON route."""
    from fastapi import Response
    from backend.core.atomistic import BundleNotPackable, pack_bundle_bin

    ctx = _atomistic_bundle_ctx(job_id)
    _design, thash, jd = ctx
    # The blob has its own disk cache, written at BUILD time (_atomistic_bundle_cached) so
    # the normal path never touches the 129 MB JSON at all.  Falling through to a repack
    # here is the one-time migration for a job whose JSON cache predates this format.
    bin_f = _atomistic_bin_cache_path(jd, thash)
    if bin_f.exists():
        try:
            return Response(
                content=bin_f.read_bytes(), media_type="application/octet-stream"
            )
        except OSError:
            pass  # unreadable/truncated → fall through and repack
    bundle = await _atomistic_bundle_cached(job_id, ctx)
    try:
        buf = await run_in_threadpool(pack_bundle_bin, bundle)
    except BundleNotPackable as e:
        raise HTTPException(409, f"bundle not packable, use the JSON route: {e}")
    try:
        bin_f.write_bytes(buf)  # so the migration happens at most once per job
    except OSError:
        pass  # cache write best-effort; correctness doesn't depend on it
    return Response(content=buf, media_type="application/octet-stream")


@router.post("/oxdna/jobs/{job_id}/display-atomistic-frames")
async def get_oxdna_display_atomistic_frames(job_id: str, align: bool = True) -> dict:
    """FAST per-frame payload for the relaxed-display atomistic rep: per-nucleotide
    rigid frames (origin + R, deformation folded) + the small non-rigid atom set,
    instead of every atom's XYZ (≈4–5× smaller).  The client holds the stamp descriptor
    (GET .../atomistic-stamp) and expands the fixed templates.  Same conf-signature
    memoisation as display-atomistic so a rep flip on the same frame re-fetches
    instantly and a still-writing run stays fresh."""
    from backend.core.oxdna_health import (
        display_frames_payload,
        _traj_file_sig,
        _display_out_get,
        _display_out_put,
    )
    from backend.core.atomistic import atomistic_reference_topology_hash

    job = _load_job(job_id)
    design, full_map, stage_name, conf_path, _ = _relaxed_full_map(
        job, align, copies=True, include_extra_bases=True, include_extensions=True
    )
    if full_map is None:
        return {"job_id": job.job_id, "ready": False}
    ck = ("dispAF", _traj_file_sig(str(conf_path)), bool(align))
    data = _display_out_get(ck)
    if data is None:
        data = await run_in_threadpool(display_frames_payload, design, full_map)
        _display_out_put(ck, data)
    return {
        "job_id": job.job_id,
        "ready": True,
        "stage_name": stage_name,
        "topology_hash": atomistic_reference_topology_hash(design),
        **data,
    }


@router.post("/oxdna/jobs/{job_id}/display-surface")
async def get_oxdna_display_surface(
    job_id: str, body: OxdnaSurfaceBody, align: bool = True
) -> dict:
    """Molecular surface mesh for the relaxed-display structure — the surface
    counterpart of GET /oxdna/jobs/{id}/display. ``surface`` = {vertices, faces,
    vertex_colors?} (same wire format as /design/features/surface-batch)."""
    from backend.core.oxdna_health import (
        frame_surface_json,
        _traj_file_sig,
        _display_out_get,
        _display_out_put,
    )

    job = _load_job(job_id)
    design, full_map, stage_name, conf_path, _ = _relaxed_full_map(
        job, align, copies=True, include_extra_bases=True, include_extensions=True
    )
    if full_map is None:
        return {"job_id": job.job_id, "ready": False}
    # Cache keyed by conf signature + align + the surface mesh params (a different
    # probe/grid/smooth is a different mesh).  Surface = atomistic rebuild + marching
    # cubes, so the re-visit saving is even larger than the atomistic case.
    sparams = (
        body.color_mode,
        round(body.probe_radius, 4),
        round(body.grid_spacing, 4),
        round(body.radius_inflate, 4),
        int(body.smooth),
        body.detail,
    )
    ck = ("dispS", _traj_file_sig(str(conf_path)), bool(align), sparams)
    data = _display_out_get(ck)
    if data is None:
        data = await run_in_threadpool(
            frame_surface_json,
            design,
            full_map,
            body.color_mode,
            body.probe_radius,
            body.grid_spacing,
            body.radius_inflate,
            body.smooth,
            None,
            body.detail,
        )
        _display_out_put(ck, data)
    return {
        "job_id": job.job_id,
        "ready": True,
        "stage_name": stage_name,
        "surface": data,
    }


@router.post("/oxdna/jobs/{job_id}/display-surface-bin")
async def get_oxdna_display_surface_bin(
    job_id: str, body: OxdnaSurfaceBody, align: bool = True
):
    """Binary counterpart of display-surface — the SAME cached mesh packed into a compact
    little-endian blob (~2× smaller than JSON, no million-number JSON.parse on the client;
    see oxdna_health.pack_surface_bin).  Empty 16-byte header (n_verts=0) = not ready."""
    from fastapi import Response
    from backend.core.oxdna_health import (
        frame_surface_json,
        pack_surface_bin,
        _traj_file_sig,
        _display_out_get,
        _display_out_put,
    )

    job = _load_job(job_id)
    design, full_map, _stage, conf_path, _ = _relaxed_full_map(
        job, align, copies=True, include_extra_bases=True, include_extensions=True
    )
    if full_map is None:
        return Response(
            content=pack_surface_bin({}), media_type="application/octet-stream"
        )
    sparams = (
        body.color_mode,
        round(body.probe_radius, 4),
        round(body.grid_spacing, 4),
        round(body.radius_inflate, 4),
        int(body.smooth),
        body.detail,
    )
    ck = ("dispS", _traj_file_sig(str(conf_path)), bool(align), sparams)
    data = _display_out_get(ck)
    if data is None:
        data = await run_in_threadpool(
            frame_surface_json,
            design,
            full_map,
            body.color_mode,
            body.probe_radius,
            body.grid_spacing,
            body.radius_inflate,
            body.smooth,
            None,
            body.detail,
        )
        _display_out_put(ck, data)
    buf = await run_in_threadpool(pack_surface_bin, data)
    return Response(content=buf, media_type="application/octet-stream")


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
    design, full_map, stage_name, _, _ = _relaxed_full_map(
        job, align, copies=True, include_extra_bases=True, include_extensions=True
    )
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
    job_id: str, body: OxdnaTrajectoryAuditBody = OxdnaTrajectoryAuditBody()
) -> dict:
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
        audit_trajectory_frames,
        design,
        stages,
        ref,
        body.frame_indices,
        max_audit=body.max_audit,
    )
    report["job_id"] = job.job_id
    return report


def _rmsf_average_frame(job, align: bool = True):
    """Shared average-structure reader for the rmsf-atomistic/surface routes.
    Returns ``(design, average_frame, rmsf_by_key)`` where ``average_frame`` is the
    per-nuc ``{key:{backbone_position(mean CM), a1, a3}}`` dict and ``rmsf_by_key``
    maps ``(helix_id, bp_index, direction) → rmsf`` (nm) so the surface can be
    coloured by flexibility.  Both are None when no sampling frames exist yet
    (mirrors GET /rmsf's not-ready paths)."""
    from backend.core.models import Design
    from backend.core.oxdna_health import production_rmsf_cached

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
    result = production_rmsf_cached(
        design,
        trajs,
        ref_conf,
        copies=True,
        align=align,
        n_trailing_extra=_capture_bead_count(job),
        trailing_extra_strand_length=_capture_strand_length(job),
    )
    if not result.get("ready"):
        return (design, None, None)
    rmsf_by_key = {
        (p["helix_id"], p["bp_index"], p["direction"]): p["rmsf"]
        for p in result.get("positions", [])
    }
    return (design, result.get("average_frame") or None, rmsf_by_key)


@router.post("/oxdna/jobs/{job_id}/rmsf-atomistic")
async def get_oxdna_rmsf_atomistic(job_id: str, align: bool = True) -> dict:
    """All-atom coordinates for the flexibility-map AVERAGE structure — the
    atomistic counterpart of GET /oxdna/jobs/{id}/rmsf. Lets the flexibility-map
    toggle drive the atomistic rep."""
    from backend.core.oxdna_health import frame_atomistic_flat

    job = _load_job(job_id)
    design, frame, _ = await run_in_threadpool(_rmsf_average_frame, job, align)
    if frame is None:
        return {"job_id": job.job_id, "ready": False}
    data = await run_in_threadpool(frame_atomistic_flat, design, frame)
    return {"job_id": job.job_id, "ready": True, "atomistic": data}


@router.post("/oxdna/jobs/{job_id}/rmsf-surface")
async def get_oxdna_rmsf_surface(
    job_id: str, body: OxdnaSurfaceBody, align: bool = True
) -> dict:
    """Molecular surface for the flexibility-map AVERAGE structure — the surface
    counterpart of GET /oxdna/jobs/{id}/rmsf.  Always coloured by per-vertex RMSF
    (``vertex_rmsf``) so the mesh shows the same rigid→flexible ramp as the beads."""
    from backend.core.oxdna_health import frame_surface_json

    job = _load_job(job_id)
    design, frame, rmsf_by_key = await run_in_threadpool(
        _rmsf_average_frame, job, align
    )
    if frame is None:
        return {"job_id": job.job_id, "ready": False}
    data = await run_in_threadpool(
        frame_surface_json,
        design,
        frame,
        "rmsf",
        body.probe_radius,
        body.grid_spacing,
        body.radius_inflate,
        body.smooth,
        rmsf_by_key,
    )
    return {"job_id": job.job_id, "ready": True, "surface": data}


@router.get("/oxdna/available")
async def get_oxdna_available() -> dict:
    """Probe for a usable oxDNA binary (mirror /md/namd-available)."""
    return oxdna_available()
