"""
Ephemeral oxDNA LIVE field routes — an in-process oxpy session that runs WITHOUT
storing a job, seeded from a completed relaxed run, re-aimable in (near) real time.

Sibling of ``routes_oxdna.py`` (the persisted job manager).  Where a field *run*
there is a stored child :class:`~backend.core.oxdna_job.OxdnaJob` (a job dir,
trajectory, resumable stages), a LIVE session here persists NOTHING but a temp
oxpy rundir: it opens :class:`~backend.physics.oxdna_live.LiveOxdnaSession` over a
run dir staged by the SAME proven field writers, burst-steps it on a background
thread, and serves the current configuration for display while the uniform field
is re-aimed live (drag the field gizmo → the running structure follows).

Route summary
─────────────
GET    /oxdna/live/available          probe for a usable, field-steerable oxpy
POST   /oxdna/live/start              seed from a completed relaxed job → start
POST   /oxdna/live/{id}/field         re-aim / rescale the running field (live)
GET    /oxdna/live/{id}/frame         current configuration → applyFemPositions list
POST   /oxdna/live/{id}/stop          stop + teardown (removes the temp rundir)

Three-Layer Law: live coordinates are *Physical-layer / display only*; they are
never written into ``Design`` topology.  The field requires ≥1 anchor (an
unanchored uniform force just streams the whole structure across the box).
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api.routes_oxdna import (
    AnchorRef,
    FieldElement,
    SurfaceElement,
    _assert_job_current,
    _load_job,
    _seed_geometry,
    _workspace,
)
from backend.core.oxdna_job import OxdnaStatus
from backend.core.oxdna_live_runner import (
    LiveSession,
    get_session,
    new_session_id,
    register,
    stop_all,
    stop_session,
)
from backend.core.oxdna_runner import (
    _latest_relaxed_conf,
    _load_snapshot_design,
    is_running,
)
from backend.physics.oxdna_interface import (
    DEFAULT_ANCHOR_STIFF,
    oxdna_backbone_site,
    pn_to_oxdna_force,
    write_configuration,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["oxdna-live"])


# ── Request models ────────────────────────────────────────────────────────────


class LiveStartRequest(BaseModel):
    """A live session composes the SAME independently-optional elements as the
    consolidated "Full Sim" run (``routes_oxdna.RunRequest``): an electric field, a
    hard surface, and anchor traps — each may be present or absent.  A field needs
    ≥1 anchor (an unanchored uniform force drifts the COM across the box); every
    other combination (anchors only / surface only / nothing = free dynamics) is
    allowed."""

    job_id: str
    field: FieldElement | None = None
    surface: SurfaceElement | None = None
    anchors: list[AnchorRef] = Field(default_factory=list)
    anchor_stiff: float = Field(DEFAULT_ANCHOR_STIFF, gt=0.0)
    burst_steps: int = Field(
        500,
        ge=1,
        le=200_000,
        description="MD steps per burst (smaller → snappier "
        "live response, larger → less overhead)",
    )


class LiveFieldRequest(BaseModel):
    field_pN: float = Field(..., gt=0.0, description="Force per nucleotide (pN)")
    dir: list[float] = Field(..., min_length=3, max_length=3)


class LiveReconfigureRequest(BaseModel):
    """Re-compose a RUNNING live session's element set (the user toggled the floor /
    E-field / anchors mid-run).  Same independently-optional elements as start —
    the engine is rebuilt over the session's CURRENT pose, so the structure responds
    from where it is (no reset)."""

    field: FieldElement | None = None
    surface: SurfaceElement | None = None
    anchors: list[AnchorRef] = Field(default_factory=list)
    anchor_stiff: float = Field(DEFAULT_ANCHOR_STIFF, gt=0.0)


# ── oxpy availability (the field-steering patch is mandatory) ─────────────────


def oxpy_live_available() -> dict:
    """Probe for an importable oxpy whose ``BaseForce`` exposes the read-write
    ``F0`` / ``dir`` bindings the live re-aim mutates (the user's local patch — see
    ``memory/project_oxpy_binding_patch.md``).  Without it a live session would die
    with ``AttributeError`` on the first re-aim, so Live is disabled."""
    try:
        import oxpy  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"oxpy not built ({exc})"}
    base = getattr(getattr(oxpy, "forces", None), "BaseForce", None)
    if base is None or not (hasattr(base, "F0") and hasattr(base, "dir")):
        return {
            "available": False,
            "reason": "oxpy is missing the F0/dir field-steering patch "
            "(see memory/project_oxpy_binding_patch.md)",
        }
    return {"available": True, "reason": "ready"}


# ── Frame builder (display payload, mirrors the batch field display) ──────────


def _make_frame_builder(design, design_ref: Path, anchor_keys):
    """Return a ``frame_builder(live_session) -> positions`` that reads the engine's
    CURRENT configuration straight from oxpy memory (no per-frame file round-trip)
    and folds it into the same applyFemPositions payload the
    ``/oxdna/jobs/{id}/display`` route emits: PBC-unwrapped, aligned to the
    origin-frame design geometry, with the anchored beads as a positional-only
    reference (translate-onto-design, NO rotation) so the field-induced reorientation
    we're studying stays visible.  The true backbone site is rendered (not the inward
    oxDNA centre of mass).

    The origin-frame reference pose and the bond-adjacency graph are CONSTANT for the
    session, so both are parsed/built ONCE here and reused every frame (the per-frame
    cost drops to: in-memory particle read + BFS unwrap + Kabsch)."""
    from backend.physics.oxdna_interface import (
        _build_unwrap_adjacency,
        read_configuration_full,
        unwrap_align_to_reference,
    )

    keys = [tuple(k) for k in anchor_keys] if anchor_keys else None
    ref = read_configuration_full(
        design_ref, design
    )  # origin-frame design pose — parsed once
    cache: dict = {}  # adjacency, built on the first frame

    def build(live_session) -> list:
        stepper = live_session.stepper
        relax = stepper.configuration_map(design)  # in-memory — no file write/parse
        if "adj" not in cache:
            cache["adj"] = _build_unwrap_adjacency(relax, design)
        full = unwrap_align_to_reference(
            relax,
            ref,
            design,
            stepper.box_nm(),
            align_keys=keys,
            rotate=keys is None,
            align=True,
            adj=cache["adj"],
        )
        return [
            {
                "helix_id": hid,
                "bp_index": bp,
                "direction": direction,
                "backbone_position": oxdna_backbone_site(
                    v["backbone_position"], v["a1"], v["a3"]
                ).tolist(),
                "nx": float(v["a1"][0]),
                "ny": float(v["a1"][1]),
                "nz": float(v["a1"][2]),
            }
            for (hid, bp, direction), v in full.items()
        ]

    return build


def _prepare_live_rundir(
    design,
    seed_conf,
    rundir,
    *,
    field,
    wall,
    anchors,
    anchor_stiff,
    steps,
    backend=None,
):
    """Stage a temp live run dir composing any combination of an electric field, a
    hard surface, and anchor traps — the SAME proven writers the consolidated
    "Full Sim" run uses (:func:`write_run_forces` + :func:`build_run_stage`), so a
    live oxpy session runs the identical physics setup.  ``field`` /``wall`` are the
    resolved element dicts (or None); ``anchors`` are anchor descriptors.

    The primary ``input`` is staged with ``backend`` (defaults to
    :func:`preferred_backend` — CUDA when a GPU is present), and a CPU ``input_cpu``
    is ALWAYS staged alongside so the stepper can fall back if the GPU run fails to
    initialise (out of memory).  Returns ``(info, backend)`` — the
    :func:`write_run_forces` info dict and the chosen primary backend."""
    import shutil

    from backend.core.oxdna_live_backend import preferred_backend
    from backend.core.oxdna_protocol import build_run_stage, render_stage_input
    from backend.physics.oxdna_interface import write_run_forces, write_topology

    if backend is None:
        backend = preferred_backend()

    rundir.mkdir(parents=True, exist_ok=True)
    write_topology(design, rundir / "topology.top")
    shutil.copy(seed_conf, rundir / "conf.dat")
    # The forces file keeps the name _OxpyStepper maps to an absolute path
    # ("field_forces.txt"); its CONTENTS are the composed field/surface/anchor blocks.
    info = write_run_forces(
        rundir / "field_forces.txt",
        design,
        rundir / "conf.dat",
        field=field,
        wall=wall,
        anchors=anchors,
        anchor_stiff=anchor_stiff,
    )
    has_forces = bool(info["has_forces"])
    efield_rec = None
    if info.get("field"):
        efield_rec = {
            "dir": info["field"]["dir"],
            "force_oxdna": info["field"]["force_oxdna"],
        }
    forces_file = "field_forces.txt" if has_forces else None

    def _render(be: str) -> str:
        spec = build_run_stage(
            name="live_run",
            steps=steps,
            external_forces=has_forces,
            forces_file=forces_file,
            efield=efield_rec,
            forces_meta={
                "has_field": bool(info.get("field")),
                "has_surface": bool(info.get("wall")),
            },
            # repulsion plane / anchor traps are absolute-coordinate forces → disable
            # oxDNA's COM diffusion-fix; a pure field (always anchored) is absolute too.
            absolute_forces=bool(wall or anchors or info.get("field")),
            backend=be,
            device="0",
        )
        return render_stage_input(spec, "topology.top", "conf.dat", forces_file)

    (rundir / "input").write_text(_render(backend))
    # Always stage a CPU fallback input (cheap) for the GPU-OOM retry path.
    (rundir / "input_cpu").write_text(
        _render("CPU") if backend != "CPU" else (rundir / "input").read_text()
    )
    return info, backend


def _resolve_live_elements(body):
    """Resolve a start/reconfigure request's enabled elements into the writers' input
    dicts (mirror /run): returns ``(field_in, field_oxdna, field_dir, wall_in,
    anchors)``.  ``field_in`` / ``wall_in`` are None when that element is off."""
    field_in = None
    field_oxdna = 0.0
    field_dir = [0.0, 1.0, 0.0]
    if body.field:
        field_oxdna = pn_to_oxdna_force(body.field.field_pN)
        field_in = {"force_oxdna": field_oxdna, "dir": list(body.field.dir)}
        field_dir = list(body.field.dir)
    wall_in = None
    if body.surface:
        wall_in = {
            "dir": body.surface.dir,
            "offset_nm": body.surface.offset_nm,
            "stiff": body.surface.stiff,
        }
    anchors = [a.model_dump(by_alias=False) for a in body.anchors]
    return field_in, field_oxdna, field_dir, wall_in, anchors


def _build_live_engine(
    design,
    seed_conf,
    rundir,
    design_ref,
    *,
    field_in,
    wall_in,
    anchors,
    anchor_stiff,
    steps,
):
    """Stage *rundir* for the given element composition (seeded from *seed_conf*) and
    build the live engine + frame builder.  Shared by /start (seed = the job's relaxed
    conf) and /reconfigure (seed = the snapshotted current pose), so both run the
    identical physics setup.  ``_prepare_live_rundir`` autodetects the backend (CUDA
    when a GPU is present) and stages a CPU fallback input; that backend is threaded
    into the stepper and returned.  Returns ``(engine, frame_builder, info, backend)``."""
    from backend.physics.oxdna_live import LiveOxdnaSession, _OxpyStepper

    info, backend = _prepare_live_rundir(
        design,
        seed_conf,
        rundir,
        field=field_in,
        wall=wall_in,
        anchors=anchors,
        anchor_stiff=anchor_stiff,
        steps=steps,
    )
    anchor_keys = [tuple(k) for k in info["anchor_keys"]]
    field_oxdna = field_in["force_oxdna"] if field_in else 0.0
    field_dir = list(field_in["dir"]) if field_in else [0.0, 1.0, 0.0]
    engine = LiveOxdnaSession(
        design,
        anchor_keys,
        stepper=_OxpyStepper(rundir, backend=backend),
        field_dir=field_dir,
        field_oxdna=field_oxdna,
    )
    builder = _make_frame_builder(design, design_ref, anchor_keys)
    return engine, builder, info, backend


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/oxdna/live/available")
async def get_oxdna_live_available() -> dict:
    return oxpy_live_available()


@router.post("/oxdna/live/start")
async def start_oxdna_live(body: LiveStartRequest) -> dict:
    """Start an ephemeral live session seeded from a completed relaxed job.

    Stages a temp run dir composing whatever elements are enabled — an electric
    field, a hard surface, anchor traps, or none (free dynamics) — with the SAME
    writers the consolidated "Full Sim" run uses, opens a persistent oxpy engine
    over it, and burst-steps it on a background thread.  Nothing is persisted — no
    ``OxdnaJob``, no stored frames — only the temp rundir (removed on stop).  A
    field with no anchor is allowed (the UI warns that an unanchored uniform force
    drifts the COM across the box, but the run is not blocked)."""
    avail = oxpy_live_available()
    if not avail["available"]:
        raise HTTPException(400, f"Live oxDNA not available: {avail['reason']}")

    parent = _load_job(body.job_id)
    if is_running(body.job_id) or parent.status != OxdnaStatus.completed:
        raise HTTPException(400, "Live needs a completed relaxed job to seed from.")
    _assert_job_current(parent)  # refuse (409) if the design changed since the relax

    ws = _workspace()
    pjd = parent.job_dir(ws)
    design = _load_snapshot_design(pjd)
    if design is None:
        raise HTTPException(
            500, "design.json snapshot missing; cannot start live session."
        )
    seed_conf, _stage = _latest_relaxed_conf(parent, ws)
    if seed_conf is None:
        raise HTTPException(
            400, "No relaxed configuration to seed the live session from."
        )

    # Resolve the enabled elements into the writer's input dicts (mirror /run).
    field_in, field_oxdna, field_dir, wall_in, anchors = _resolve_live_elements(body)

    sid = new_session_id()
    rundir = ws / "live_sessions" / sid
    rundir.mkdir(parents=True, exist_ok=True)
    # Origin-frame design reference for display alignment (the field-off pose),
    # mirroring routes_oxdna._design_ref_conf — NOT the drifted seed conf.  Written
    # before the engine build so the frame builder can parse it.
    design_ref = rundir / "design_ref.dat"
    write_configuration(design, _seed_geometry(design), design_ref)

    # _build_live_engine autodetects the backend (CUDA when a GPU is present, with a
    # CPU fallback input staged) and returns it for the response.
    engine, builder, info, backend = _build_live_engine(
        design,
        seed_conf,
        rundir,
        design_ref,
        field_in=field_in,
        wall_in=wall_in,
        anchors=anchors,
        anchor_stiff=body.anchor_stiff,
        steps=body.burst_steps,
    )
    # A field with no (or an unresolvable) anchor selection is allowed — the COM
    # drift is surfaced as a UI warning, not blocked.

    live = LiveSession(
        sid,
        engine,
        frame_builder=builder,
        field_oxdna=field_oxdna,
        field_dir=field_dir,
        burst_steps=body.burst_steps,
        rundir=rundir,
        design=design,
        design_ref=design_ref,
    )

    # One in-process oxpy engine at a time — tear down any prior session first.
    stop_all()
    register(live)
    live.start()
    logger.info(
        "start_oxdna_live: session=%s parent_job=%s field=%s surface=%s anchored=%d",
        sid,
        body.job_id,
        bool(field_in),
        bool(wall_in),
        info["n_anchored"],
    )
    return {
        "session_id": sid,
        "status": live.status,
        "n_anchored": info["n_anchored"],
        "backend": backend,
    }


@router.post("/oxdna/live/{session_id}/field")
async def update_oxdna_live_field(session_id: str, body: LiveFieldRequest) -> dict:
    """Re-aim / rescale the running field LIVE (applied before the next burst)."""
    live = get_session(session_id)
    if live is None:
        raise HTTPException(404, f"live session {session_id!r} not found")
    live.set_field(field_oxdna=pn_to_oxdna_force(body.field_pN), field_dir=body.dir)
    return {"ok": True}


@router.post("/oxdna/live/{session_id}/reconfigure")
async def reconfigure_oxdna_live(session_id: str, body: LiveReconfigureRequest) -> dict:
    """Re-compose a running live session (floor / E-field / anchors toggled mid-run).

    The engine is rebuilt over the session's CURRENT pose with the new forces — the
    structure responds from where it is (no reset to the relaxed seed).  A live field
    with no anchor is allowed (the UI warns of COM drift).  Applied before the next
    burst on the worker thread."""
    live = get_session(session_id)
    if live is None:
        raise HTTPException(404, f"live session {session_id!r} not found")

    design = live.design
    rundir = live.rundir
    if design is None or rundir is None:
        raise HTTPException(400, "This live session does not support reconfigure.")
    design_ref = live.design_ref or (rundir / "design_ref.dat")
    steps = live.burst_steps

    field_in, field_oxdna, field_dir, wall_in, anchors = _resolve_live_elements(body)

    # Pre-validate the anchor selection on the request thread (resolve_anchor_particles
    # needs only the design, not the conf) so a stale/empty field anchor returns 400
    # instead of erroring the worker mid-rebuild.
    if field_in:
        from backend.physics.oxdna_interface import resolve_anchor_particles

        parts, _keys = resolve_anchor_particles(design, anchors)
        if not parts:
            raise HTTPException(
                400,
                "The anchor selection resolved to no nucleotides — a live field "
                "needs ≥1 anchor to hold the structure against the field.",
            )

    def rebuild():
        # Runs on the worker thread AFTER it snapshots the current pose to
        # reconfig_seed.dat — re-stage the rundir for the new composition + build the
        # fresh engine seeded from that pose.
        engine, builder, _info, _backend = _build_live_engine(
            design,
            rundir / "reconfig_seed.dat",
            rundir,
            design_ref,
            field_in=field_in,
            wall_in=wall_in,
            anchors=anchors,
            anchor_stiff=body.anchor_stiff,
            steps=steps,
        )
        return engine, builder

    live.reconfigure(rebuild, field_oxdna=field_oxdna, field_dir=field_dir)
    logger.info(
        "reconfigure_oxdna_live: session=%s field=%s surface=%s anchors=%d",
        session_id,
        bool(field_in),
        bool(wall_in),
        len(anchors),
    )
    return {"ok": True}


@router.get("/oxdna/live/{session_id}/frame")
async def get_oxdna_live_frame(session_id: str) -> dict:
    """Latest captured configuration as an applyFemPositions update list."""
    live = get_session(session_id)
    if live is None:
        raise HTTPException(404, f"live session {session_id!r} not found")
    return live.frame()


@router.post("/oxdna/live/{session_id}/stop")
async def stop_oxdna_live(session_id: str) -> dict:
    """Stop the session and remove its temp rundir (idempotent)."""
    stopped = stop_session(session_id)
    return {"ok": True, "stopped": stopped}
