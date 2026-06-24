"""Headless (mouse-free) oxDNA relaxation — the physical-layer entry point.

Tiers 0–4 of the design-automation loop drive the *topological* and *geometric*
layers headlessly (``headless_build`` / ``headless_assembly_build``).  This module
opens the *physical* layer: it drives the real oxDNA job routes from a scratch
session — ``create_oxdna_job`` → ``start_oxdna_job`` → poll-to-terminal → optional
``append_oxdna_production`` → ``get_oxdna_display`` — so a script (or an AI builder)
can relax a design and recover the relaxed geometry without a browser, exactly as
the Dynamics panel does with the mouse.

Each wrapper imports the *exact* route handler it drives (e.g.
``create_oxdna_job as _route_create_oxdna_job``) and runs it — it does NOT
re-implement the staging/run logic.  ``oxdna_coverage_report`` (in
``tests/automation_harness.py``) tracks this by function identity, mirroring the
design/assembly coverage audit.

**Three-Layer Law (load-bearing here).** oxDNA output is *Physical-layer only*: it
is read back as a position map (PBC-unwrapped + Kabsch-aligned to the design) and
**never written into ``Design`` topology**.  These wrappers expose only the read
path — nothing here mutates a design from a relaxed configuration.

Isolation: a relaxation runs against whatever workspace dir the caller passes (the
route handlers read the module-global ``routes_oxdna._WORKSPACE_DIR``; we redirect
it for the duration of each call), and ``create_oxdna_job`` reads the active design
from an isolated throwaway document, so a scripted relaxation never disturbs the
real workspace or the caller's active design.  In tests the mock oxDNA binary
(``$OXDNA_BIN``) makes the whole path deterministic without a GPU; a real run is
gated by ``find_oxdna()``.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import time
from pathlib import Path

from backend.api import doc_context
from backend.api import routes_oxdna
from backend.api import state as design_state
from backend.api.routes_oxdna import (
    CreateOxdnaJobRequest,
    FieldRequest,
    ProductionRequest,
    append_oxdna_field as _route_append_field,
    append_oxdna_production as _route_append_production,
    create_oxdna_job as _route_create_oxdna_job,
    get_oxdna_display as _route_get_display,
    get_oxdna_rmsf as _route_get_rmsf,
    roll_oxdna_job_design as _route_roll_design,
    start_oxdna_job as _route_start_job,
)
from backend.core.models import Design
from backend.core.oxdna_job import OxdnaJob, OxdnaStatus
from backend.core.oxdna_protocol import (
    DEFAULT_EQUIL_STEPS,
    DEFAULT_MC_STEPS,
    DEFAULT_MD_RELAX_STEPS,
    MAX_RELAX_RETRIES,
)
from backend.physics.oxdna_interface import DEFAULT_ANCHOR_STIFF

_scratch_counter = itertools.count()

_TERMINAL = (OxdnaStatus.completed, OxdnaStatus.failed, OxdnaStatus.stopped)

# Standard-grade relaxation parameters for a REAL-engine specimen build.  The
# ``create_job`` / ``build_field_specimen`` defaults (mc=100 / md_relax=100 /
# equil=100, gate 0.0, 0 retries) are tuned for the identity MOCK binary and do NOT
# re-anneal on the real engine: oxDNA drops base-pairing early in md_relax and needs
# the full ~1e6-step md_relax for the mutual traps to pull the duplex back together
# (verified — a 42 bp duplex re-anneals to 42/42 only with md_relax≈1e6; 1e5 leaves it
# melted; see ``project_oxdna_relaxation`` 2026-06-23).  A REAL Tier-6 run passes
# ``**STANDARD_RELAX_PARAMS`` to ``build_field_specimen`` explicitly (the mock defaults
# stay the default so GPU-free orchestration tests — whose mock cost scales with step
# count — stay fast).
STANDARD_RELAX_PARAMS: dict = {
    "mc_steps": DEFAULT_MC_STEPS,              # 1_000
    "md_relax_steps": DEFAULT_MD_RELAX_STEPS,  # 1_000_000 — the re-anneal needs this
    "equil_steps": DEFAULT_EQUIL_STEPS,        # 100_000
    "min_bp_retained": 0.5,                    # real quality gate (catches under-relax)
    "max_relax_retries": MAX_RELAX_RETRIES,    # escalate-and-retry a stuck md_relax
}


# ── Isolation context managers ────────────────────────────────────────────────

@contextlib.contextmanager
def _use_workspace(workspace):
    """Temporarily point the oxDNA routes' workspace at ``workspace``.

    The route handlers read the module-global ``routes_oxdna._WORKSPACE_DIR`` via
    ``_workspace()``; a headless caller redirects it at a throwaway dir so a
    scripted relaxation never touches the real workspace, restoring it on exit.
    """
    prev = routes_oxdna._WORKSPACE_DIR
    routes_oxdna._WORKSPACE_DIR = Path(workspace)
    try:
        yield
    finally:
        routes_oxdna._WORKSPACE_DIR = prev


@contextlib.contextmanager
def _scratch_design(design: Design):
    """Bind ``design`` as the active design of an isolated throwaway document.

    ``create_oxdna_job`` reads ``design_state.get_or_404()``; this scopes a fresh
    doc (mirrors ``headless_build.scratch_session``) so the caller's active design
    and undo history are untouched.
    """
    doc_id = f"__headless_oxdna_{next(_scratch_counter)}__"
    token = doc_context.set_current_doc(doc_id)
    try:
        design_state.set_design(design)
        yield
    finally:
        doc_context.reset_current_doc(token)
        design_state.drop_doc(doc_id)


@contextlib.contextmanager
def _scratch_job_design(job_id: str, workspace):
    """Scope a job's frozen snapshot design as the active design while a route runs.

    The oxDNA staleness guard (``routes_oxdna._assert_job_current``) refuses a
    live/production run when the CURRENT active design diverges from the job — a UI
    safeguard.  In headless automation there is no UI design; a field/production run
    logically operates on the job's OWN design, so bind that as the active design for
    the call (matching fingerprint → guard passes), instead of leaving whatever
    happens to be in the default document to trip it.  No snapshot (legacy job) → no
    scope (the guard no-ops on an unknown fingerprint)."""
    snap = None
    try:
        from backend.core.oxdna_job import OxdnaJob
        from backend.core.oxdna_runner import _load_snapshot_design
        job = OxdnaJob.load(job_id, Path(workspace))
        snap = _load_snapshot_design(job.job_dir(Path(workspace)))
    except Exception:
        snap = None
    if snap is None:
        yield
    else:
        with _scratch_design(snap):
            yield


# ── Route-driving wrappers ────────────────────────────────────────────────────

def create_job(
    design: Design,
    workspace,
    *,
    autostart: bool = False,
    backend: str = "CPU",
    device: str = "0",
    salt_concentration: float = 0.5,
    mc_steps: int = 100,
    md_relax_steps: int = 100,
    equil_steps: int = 100,
    min_bp_retained: float = 0.0,
    max_relax_retries: int = 0,
    design_source_path: str | None = None,
) -> dict:
    """Create + prepare a 3-stage relaxation job from ``design`` (mirrors
    ``POST /oxdna/jobs``).  Returns the job dict; read ``["job_id"]``.

    Drives the real ``create_oxdna_job`` handler — the same staging the Dynamics
    panel triggers.  ``min_bp_retained`` defaults to ``0.0`` because the mock binary
    does not actually relax (it copies the input conf), so the base-pair-retention
    gate must be off for headless orchestration tests; a real GPU run should raise
    it back to ~0.5.  ``max_relax_retries`` defaults to ``0`` (no escalate-and-retry)
    for the same reason — headless runs are deterministic short validation passes, and
    the equil-readiness escalation would otherwise spin to exhaustion on the mock's
    unrelaxed conf; a real headless relaxation can pass a positive budget.  Requires
    ``find_oxdna()`` to resolve a binary (set ``$OXDNA_BIN``), and ``design`` to be
    fully sequenced (oxDNA rejects undefined bases).
    """
    body = CreateOxdnaJobRequest(
        backend=backend,
        device=device,
        salt_concentration=salt_concentration,
        mc_steps=mc_steps,
        md_relax_steps=md_relax_steps,
        equil_steps=equil_steps,
        min_bp_retained=min_bp_retained,
        max_relax_retries=max_relax_retries,
        autostart=autostart,
        design_source_path=design_source_path,
    )
    with _scratch_design(design), _use_workspace(workspace):
        return asyncio.run(_route_create_oxdna_job(body))


def start_relaxation(job_id: str, workspace) -> dict:
    """Start or resume a queued/stopped/failed job (mirrors
    ``POST /oxdna/jobs/{id}/start``)."""
    with _use_workspace(workspace):
        return asyncio.run(_route_start_job(job_id))


def append_production(job_id: str, workspace, *, steps: int = 1000) -> dict:
    """Append an unbiased MD production stage to a completed job (mirrors
    ``POST /oxdna/jobs/{id}/production``).  Continues from the relaxed structure."""
    with _use_workspace(workspace), _scratch_job_design(job_id, workspace):
        return asyncio.run(
            _route_append_production(job_id, ProductionRequest(steps=steps))
        )


def append_field(job_id: str, workspace, *, field_pN: float, dir, anchors: list[dict],
                 steps: int = 2000, anchor_stiff: float = DEFAULT_ANCHOR_STIFF) -> dict:
    """Append an electric-field stage to a completed job (mirrors
    ``POST /oxdna/jobs/{id}/field``).  ``anchors`` are descriptors resolved to
    pinned nucleotides (e.g. ``{'kind':'domain','strand_id':…,'domain_index':0}``
    or ``{'kind':'overhang','id':…}``)."""
    with _use_workspace(workspace), _scratch_job_design(job_id, workspace):
        return asyncio.run(_route_append_field(job_id, FieldRequest(
            field_pN=field_pN, dir=list(dir), anchors=anchors,
            steps=steps, anchor_stiff=anchor_stiff)))


def roll_job_to_run_state(job_id: str, workspace) -> dict:
    """Roll the ACTIVE design back to the state oxDNA job ``job_id`` was relaxed at
    (mirrors ``POST /oxdna/jobs/{id}/roll-design``) — the headless analog of the
    out-of-date "Roll & run" button.

    Operates on the **live** active design (NOT a job-scoped scratch design): it
    saves the current edits as a "Return to latest" loadout branch, then seeks the
    feature-log cursor to the job's run position so the full log is kept, the model
    reverts to the job's state, and the out-of-date flag clears.  Returns the roll
    response (carries ``return_loadout_id`` — pass it to
    :func:`backend.api.headless_build.return_to_latest`).

    Pin the whole simulate→edit→roll→return contract with
    :func:`tests.automation_harness.assert_roll_return_lifecycle`.
    """
    with _use_workspace(workspace):
        return asyncio.run(_route_roll_design(job_id))


def read_relaxed_positions(job_id: str, workspace) -> dict:
    """Read the last relaxed frame back as a position list (mirrors
    ``GET /oxdna/jobs/{id}/display``).

    PBC-unwrapped + Kabsch-aligned to the design via
    ``read_configuration_unwrapped``.  Returns ``{ready, positions, n_positions, …}``
    — *Physical-layer only*; the positions are never written back into topology.
    """
    with _use_workspace(workspace):
        return asyncio.run(_route_get_display(job_id))


def read_flexibility_map(job_id: str, workspace) -> dict:
    """Read the noise-averaged mean structure + RMSF flexibility map of a job's
    production run (mirrors ``GET /oxdna/jobs/{id}/rmsf``).

    Pools every production-trajectory frame, PBC-unwraps + Kabsch-aligns each to
    the design reference, and returns the per-nucleotide MEAN backbone position
    plus a ``confidence`` block (``{n_frames, rel_error, preliminary}``) — the
    statistical reliability of the map given how many frames were pooled.  Prefer
    this over the single relaxed frame (:func:`read_relaxed_positions`) for a
    *measurement*: the mean cancels thermal noise and the confidence flags a
    too-short run.  Requires a prior :func:`append_production` run (the rmsf route
    returns ``{ready: False}`` until production frames exist).

    Returns ``{ready, positions, confidence, n_frames, …}`` — *Physical-layer
    only*; the mean positions are never written back into topology.
    """
    with _use_workspace(workspace):
        return asyncio.run(_route_get_rmsf(job_id))


# ── Polling + one-call orchestration ──────────────────────────────────────────

def wait_for_terminal(job_id: str, workspace, *, timeout: float = 30.0,
                      poll_s: float = 0.05) -> OxdnaJob:
    """Poll the on-disk job until a terminal status (completed / failed / stopped)
    or ``timeout`` elapses.  Returns the loaded :class:`OxdnaJob` either way.

    The background relaxation runs in a daemon thread the route spawned; we load the
    job straight from ``workspace`` (explicit, no global override needed) so polling
    is independent of any active session.
    """
    workspace = Path(workspace)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = OxdnaJob.load(job_id, workspace)
        if job.status in _TERMINAL:
            return job
        time.sleep(poll_s)
    return OxdnaJob.load(job_id, workspace)


def run_relaxation(design: Design, workspace, *, timeout: float = 30.0,
                   **params) -> OxdnaJob:
    """One-call headless relaxation: create (no autostart) → start → poll to
    terminal.  Returns the terminal :class:`OxdnaJob`.

    Drives the real ``create_oxdna_job`` + ``start_oxdna_job`` handlers (so both
    register as covered by function identity).  ``params`` forwards to
    :func:`create_job` (``mc_steps`` / ``md_relax_steps`` / ``equil_steps`` /
    ``min_bp_retained`` / ``backend`` / …).
    """
    info = create_job(design, workspace, autostart=False, **params)
    job_id = info["job_id"]
    start_relaxation(job_id, workspace)
    return wait_for_terminal(job_id, workspace, timeout=timeout)


def run_field(design: Design, workspace, *, field_pN: float, dir, anchors: list[dict],
              timeout: float = 30.0, field_steps: int = 2000, **relax_params) -> OxdnaJob:
    """One-call headless field run: relax → append a field stage → poll to terminal.

    Returns the terminal :class:`OxdnaJob`.  If relaxation does not complete it
    returns that job unchanged (no field stage appended).  ``relax_params`` forward
    to :func:`create_job`; ``anchors`` are anchor descriptors (see
    :func:`append_field`)."""
    parent = run_relaxation(design, workspace, timeout=timeout, **relax_params)
    if parent.status != OxdnaStatus.completed:
        return parent
    child = append_field(parent.job_id, workspace, field_pN=field_pN, dir=dir,
                         anchors=anchors, steps=field_steps)
    return wait_for_terminal(child["job_id"], workspace, timeout=timeout)


def run_field_validation(design: Design, workspace, *, field_pN: float, dir,
                         anchors: list[dict], timeout: float = 30.0,
                         field_steps: int = 2000, **relax_params) -> dict:
    """End-to-end automatable field validation: relax → field → measure the
    deflection oracle.  Returns ``{"job": OxdnaJob, "response": dict | None}``
    where ``response`` is :func:`field_response_from_confs` over the field stage's
    ``last_conf`` vs the prior (relaxed) stage's — i.e. did the anchors hold and
    the rest deflect ALONG the field.  ``response`` is None if the run did not
    complete or there is no pre-field stage to reference."""
    job = run_field(design, workspace, field_pN=field_pN, dir=dir, anchors=anchors,
                    timeout=timeout, field_steps=field_steps, **relax_params)
    if job.status != OxdnaStatus.completed or not job.stages:
        return {"job": job, "response": None}
    from backend.core.oxdna_health import field_response_from_confs
    ws = Path(workspace)
    # ``job`` is the field CHILD: its field stage's last_conf vs its seed conf.dat
    # (the relaxed structure the field started from) — the field-off reference.
    field_conf = job.stage_dir(ws, job.stages[-1].name) / "last_conf.dat"
    ref_conf = job.job_dir(ws) / "conf.dat"
    response = field_response_from_confs(
        design, field_conf, ref_conf, field_dir=list(dir), anchors=anchors)
    return {"job": job, "response": response}


def build_field_specimen(spec_or_design, workspace, *, anchor: dict,
                         overhang: dict | None = None, sequence: bool = True,
                         scaffold_name: str = "M13mp18", timeout: float = 30.0,
                         **relax_params) -> dict:
    """Compose the entire build→field-ready chain into ONE headless call (AF-18,
    Tier 6): a design → (optional overhang) → fully sequenced → relaxed → with a
    designated field **anchor** resolved to pinned nucleotides.  Returns
    ``{"design": Design, "job": OxdnaJob, "anchor_keys": [...], "anchor": dict}`` —
    a specimen ready to run an electric-field experiment (subject it to a field with
    :func:`append_field` / :func:`run_field`, anchoring ``anchor``).

    ``spec_or_design`` is either a ready :class:`~backend.core.models.Design` (used
    as-is, deep-copied) or a declarative build-spec dict (lowered via
    :func:`headless_spec_build.build_design`, which does any routing the spec
    describes).  The topological/geometric steps run in an isolated scratch session
    (the active design + undo history are untouched):

    1. **overhang** — if ``overhang`` is given, extrude it (``hb.overhang_extrude``).
       The overhang's nucleotides are a **spec input** the caller provides; this
       wrapper never *infers* which nucleotides form the overhang geometrically
       (the ASK-FIRST DNA-topology rule).
    2. **sequence** — ``hb.full_sequence`` so the design carries a complete sequence
       (oxDNA rejects any undefined base); pass ``sequence=False`` if the input is
       already fully sequenced.
    3. **anchor** — resolve the ``anchor`` descriptor (overhang / cluster / domain,
       see :func:`append_field`) to particle indices + keys via
       :func:`resolve_anchor_particles` on the *final* design.  Raises ``ValueError``
       if it resolves to nothing — an un-anchorable specimen would just stream across
       the box under a uniform field (the COM-drift gotcha), so it is not field-ready.
    4. **relax** — :func:`run_relaxation` (physical layer; relaxed coords are read
       back as a position map, never written into ``Design`` — the Three-Layer Law).

    ``relax_params`` forward to :func:`create_job` (``min_bp_retained`` / step counts
    / ``backend`` / …).  **For a REAL-engine run, pass ``**STANDARD_RELAX_PARAMS``**
    (md_relax≈1e6) and a generous ``timeout`` (a real relaxation is minutes):

        hox.build_field_specimen(design, ws, anchor=a, sequence=False,
                                 backend="CUDA", timeout=900.0,
                                 **hox.STANDARD_RELAX_PARAMS)

    The bare ``create_job`` defaults (mc=100/md=100/equil=100) are MOCK-tuned and do
    **not** re-anneal on the real engine — the duplex melts early in md_relax and only
    recovers over the long md_relax (verified — see :data:`STANDARD_RELAX_PARAMS`).
    They are kept as the default so GPU-free orchestration tests (which drive the mock
    binary, whose cost scales with step count) stay fast; the *real* Tier-6 path opts
    into the standard grade explicitly.
    Pin the result with :func:`tests.automation_harness.assert_field_ready_specimen`.
    """
    from backend.api import headless_build as hb
    from backend.physics.oxdna_interface import resolve_anchor_particles

    if isinstance(spec_or_design, Design):
        base = spec_or_design.model_copy(deep=True)
    else:
        from backend.api import headless_spec_build as hs
        base = hs.build_design(spec_or_design)

    with hb.scratch_session(base.lattice_type):
        design_state.set_design(base)
        if overhang is not None:
            hb.overhang_extrude(**overhang)
        if sequence:
            hb.full_sequence(scaffold_name=scaffold_name)
        design = design_state.get_or_404().model_copy(deep=True)

    parts, anchor_keys = resolve_anchor_particles(design, [anchor])
    if not parts:
        raise ValueError(
            f"build_field_specimen: anchor {anchor!r} resolved to no nucleotides — "
            "the specimen cannot be anchored for a field run")

    job = run_relaxation(design, workspace, timeout=timeout, **relax_params)
    return {"design": design, "job": job, "anchor_keys": anchor_keys, "anchor": anchor}


# ── LIVE field: persistent in-process oxpy session, re-aimable mid-run (AF-21) ──

def _prepare_field_rundir(design, seed_conf, rundir, *, field_pN, dir, anchors,
                          anchor_stiff, steps):
    """Stage a field run dir (``topology.top`` / ``conf.dat`` / ``field_forces.txt``
    / ``input``) reusing the SAME proven writers the batch field stage uses, so a
    live oxpy session runs the identical physics setup.  ``seed_conf`` is the
    field-off (relaxed) configuration the field starts from.  Returns the field
    magnitude in oxDNA units."""
    import shutil

    from backend.core.oxdna_protocol import build_field_stage, render_stage_input
    from backend.physics.oxdna_interface import (
        pn_to_oxdna_force, write_field_forces, write_topology,
    )

    rundir = Path(rundir)
    rundir.mkdir(parents=True, exist_ok=True)
    write_topology(design, rundir / "topology.top")
    shutil.copy(seed_conf, rundir / "conf.dat")
    field_oxdna = pn_to_oxdna_force(field_pN)
    # Anchors are mandatory (a uniform field on a free body just streams the COM
    # across the box) — write_field_forces raises if the selection is empty.
    write_field_forces(rundir / "field_forces.txt", design, rundir / "conf.dat",
                       field_oxdna=field_oxdna, field_dir=list(dir), anchors=anchors,
                       anchor_stiff=anchor_stiff)
    spec = build_field_stage(name="live_field", field_oxdna=field_oxdna,
                             field_dir=list(dir), forces_file="field_forces.txt",
                             steps=steps, backend="CPU", device="0")
    (rundir / "input").write_text(
        render_stage_input(spec, "topology.top", "conf.dat", "field_forces.txt"))
    return field_oxdna


def run_live_field(specimen, workspace, *, field_pN: float, dir, total_steps: int = 4000,
                   n_bursts: int = 4, mutate_dir=None, anchor_stiff=DEFAULT_ANCHOR_STIFF,
                   session=None, rundir=None) -> dict:
    """Drive a PERSISTENT in-process oxpy field run over a built specimen — the
    interactive analog of :func:`run_field` (AF-21, Tier 6).  The engine loads once
    and steps in ``n_bursts`` bursts (``total_steps`` total); if ``mutate_dir`` is
    given the field is **re-aimed** to it at the half-way point (the live mutation),
    proving the structure follows the steered field.  Returns equilibrium
    observables in the schema the parity oracle compares:

    ``{"observables": {alignment_nm, radius_of_gyration_nm, bp_retention, …},
       "confidence": <bursts>, "field_dir": [...], "mutation": {...} | None}``

    ``specimen`` is a :func:`build_field_specimen` result (``design`` + relaxed
    parent ``job`` + ``anchor`` + ``anchor_keys``).  ``session`` is an injectable
    :class:`~backend.physics.oxdna_live.LiveOxdnaSession`-like object — GPU-free
    tests pass a mock stepper; left ``None`` it builds a real oxpy session over a
    freshly-staged run dir (needs the oxpy build).

    The ``mutation`` block measures the free body's deflection ALONG the *new*
    field vector before vs after the re-aim (``followed`` = it increased) — the
    can-go-red signal for "the field actually steers the body".  Physical-layer
    only (reads geometry, never writes ``Design``); magnitudes → direction-agnostic.
    """
    design = specimen["design"]
    anchor_keys = specimen["anchor_keys"]
    ws = Path(workspace)

    if session is None:
        from backend.physics.oxdna_live import LiveOxdnaSession, _OxpyStepper

        job = specimen["job"]
        seed_conf = job.stage_dir(ws, job.stages[-1].name) / "last_conf.dat"
        rd = Path(rundir) if rundir else ws / f"live_field_{next(_scratch_counter)}"
        field_oxdna = _prepare_field_rundir(
            design, seed_conf, rd, field_pN=field_pN, dir=dir,
            anchors=[specimen["anchor"]], anchor_stiff=anchor_stiff, steps=total_steps)
        session = LiveOxdnaSession(design, anchor_keys, stepper=_OxpyStepper(rd),
                                   field_dir=list(dir), field_oxdna=field_oxdna)

    burst = max(1, total_steps // max(1, n_bursts))
    phase1 = (n_bursts // 2) if mutate_dir is not None else n_bursts

    with session:
        session.set_field(field_dir=list(dir))   # field on, our magnitude + dir
        for _ in range(phase1):
            session.run(burst)

        mutation = None
        if mutate_dir is not None:
            before = session.equilibrium_observables(field_dir=list(mutate_dir))
            session.set_field(field_dir=list(mutate_dir))   # the LIVE re-aim
            for _ in range(n_bursts - phase1):
                session.run(burst)
            after = session.equilibrium_observables(field_dir=list(mutate_dir))
            mutation = {
                "from_dir": list(dir),
                "to_dir": list(mutate_dir),
                "proj_on_to_before_nm": before["alignment_nm"],
                "proj_on_to_after_nm": after["alignment_nm"],
                "followed": after["alignment_nm"] > before["alignment_nm"] + 1e-9,
            }

        observables = session.equilibrium_observables()

    return {"observables": observables, "confidence": int(n_bursts),
            "field_dir": list(mutate_dir) if mutate_dir is not None else list(dir),
            "mutation": mutation}


def steer_field_session(session, waypoints, *, steps_per_waypoint: int = 1000) -> dict:
    """Drive a SEQUENCE of field waypoints over a persistent live session — the
    headless analog of a user dragging the field gizmo through a path (AF-22, Tier 6).

    Where :func:`run_live_field` re-aims the field ONCE (the AF-21 mutation), this
    walks an arbitrary list of waypoints: for each one it re-aims the field to the
    waypoint's direction (and optional magnitude), runs a burst, and records the free
    body's deflection ALONG that waypoint's field vector measured *before* the burst
    (the pose the previous waypoint left) and *after* it.  The rising before→after
    projection is the field-following signal — the structure chasing the steered
    field — checked by :func:`assert_live_field_following`.

    ``session`` is an un-entered
    :class:`~backend.physics.oxdna_live.LiveOxdnaSession`-like object (GPU-free tests
    inject a mock stepper; a real one needs the oxpy build).  Each ``waypoints`` entry
    is a dict ``{"dir": [x,y,z], "field_pN": <opt>, "steps": <opt>}`` — ``dir`` is the
    new field direction; ``field_pN`` re-scales the magnitude for that leg (else the
    session's current magnitude carries over); ``steps`` overrides ``steps_per_waypoint``
    for that leg.

    Returns ``{"timeline": [per-waypoint dict, …], "n_waypoints": N}`` where each entry
    carries ``{field_dir, steps, proj_before_nm, proj_after_nm, alignment_nm,
    bp_retention, radius_of_gyration_nm, followed}``.  ``alignment_nm`` is the deflection
    along the *current* waypoint's vector (= ``proj_after_nm``).  Physical-layer only
    (reads geometry, never writes ``Design``); magnitudes/signed-projections only →
    direction-agnostic (no handedness reasoning).
    """
    from backend.physics.oxdna_interface import pn_to_oxdna_force

    if not waypoints:
        raise ValueError("steer_field_session: no waypoints to steer through")

    timeline: list[dict] = []
    with session:
        for wp in waypoints:
            new_dir = list(wp["dir"])
            # Deflection along the NEW vector at the pose the previous leg left.
            before = session.equilibrium_observables(field_dir=new_dir)
            set_kw = {"field_dir": new_dir}
            if wp.get("field_pN") is not None:
                set_kw["field_oxdna"] = pn_to_oxdna_force(float(wp["field_pN"]))
            session.set_field(**set_kw)
            steps = int(wp.get("steps", steps_per_waypoint))
            session.run(steps)
            after = session.equilibrium_observables(field_dir=new_dir)
            timeline.append({
                "field_dir": new_dir,
                "steps": steps,
                "proj_before_nm": before["alignment_nm"],
                "proj_after_nm": after["alignment_nm"],
                "alignment_nm": after["alignment_nm"],
                "bp_retention": after["bp_retention"],
                "radius_of_gyration_nm": after["radius_of_gyration_nm"],
                "followed": after["alignment_nm"] > before["alignment_nm"] + 1e-9,
            })

    return {"timeline": timeline, "n_waypoints": len(timeline)}


# ── Field SWEEP: a (|E|, direction) response surface over one specimen (AF-20) ──

def _measure_field_cell(job, workspace, design, field_dir, anchor_keys, *,
                        melt_floor: float, min_confidence: int) -> dict | None:
    """Reduce ONE terminal field child job to a sweep-cell verdict via the AF-19
    time-resolved measure.  Returns ``None`` (skip) only when the job did not
    complete or wrote no field trajectory (so the caller can record a no-silent-
    truncation note); otherwise a dict of the *measured* observables:
    ``{tau_steps, tau_frames, converged, aligned, bp_min, bp_final, n_frames,
    melted, confident, destructive}``.  ``destructive`` is the convenience verdict
    (``not (aligned and bp_min >= melt_floor)``) — the oracle recomputes it from
    the raw fields, so it is narrative here, not load-bearing.
    """
    from backend.core.oxdna_health import measure_field_equilibration
    from backend.physics.oxdna_interface import read_trajectory_frames_full

    if job.status != OxdnaStatus.completed:
        return None
    ws = Path(workspace)
    stage = next((s for s in job.stages if s.kind == "field"), None)
    if stage is None:
        return None
    traj = job.stage_dir(ws, stage.name) / "trajectory.dat"
    if not traj.exists():
        return None

    frames = read_trajectory_frames_full(traj, design)
    n_frames = len(frames)
    confident = n_frames >= min_confidence
    if n_frames < 2:
        return {"tau_steps": None, "tau_frames": None, "converged": False,
                "aligned": False, "bp_min": 0.0, "bp_final": 0.0,
                "n_frames": n_frames, "melted": True, "confident": False,
                "destructive": True}

    total_steps = getattr(stage, "steps", None)
    steps_per_frame = (total_steps / n_frames) if total_steps else 1.0
    eq = measure_field_equilibration(frames, field_dir, anchor_keys, design=design,
                                     steps_per_frame=steps_per_frame,
                                     melt_floor=melt_floor)
    aligned = bool(eq["converged"] and eq["tau_steps"] is not None
                   and eq["tau_steps"] > 0 and confident)
    bp_min = eq["bp_min"]
    destructive = not (aligned and bp_min >= melt_floor)
    return {"tau_steps": eq["tau_steps"], "tau_frames": eq["tau_frames"],
            "converged": bool(eq["converged"]), "aligned": aligned,
            "bp_min": bp_min, "bp_final": eq["bp_timecourse"][-1],
            "n_frames": n_frames, "melted": bool(eq["melted"]),
            "confident": confident, "destructive": destructive}


def sweep_field_response(specimen: dict, intensities_pN, directions, workspace, *,
                         field_steps: int = 2000, melt_floor: float = 0.5,
                         min_confidence: int = 10, timeout: float = 30.0,
                         anchor_stiff: float = DEFAULT_ANCHOR_STIFF) -> dict:
    """Sweep an electric field over a grid of ``(|E|, direction)`` and assemble the
    per-cell *response surface* of a single field-ready specimen (AF-20, Tier 6).

    ``specimen`` is the dict :func:`build_field_specimen` returns (``design`` +
    relaxed ``job`` + ``anchor`` + ``anchor_keys``).  For every intensity (pN) ×
    direction cell, a **child field job** is branched off the SAME relaxed parent
    (reusing the :func:`append_field` child-job spawn — the parent is relaxed once,
    so each cell measures the same starting structure under a different field), run
    to terminal, and reduced by the AF-19 time-resolved measure
    (:func:`~backend.core.oxdna_health.measure_field_equilibration`) to a cell
    verdict carrying the equilibration time τ, the aligned/converged flags, and the
    base-pair-retention floor (the melt watch).

    Returns ``{"map": {(pN, dir_tuple): cell}, "skipped": [(pN, dir_tuple), …],
    "intensities_pN": [...], "directions": [...], "melt_floor": …}``.  A cell whose
    field job failed or wrote no trajectory is recorded in ``skipped`` (NOT silently
    dropped — the sweep grid stays auditable).  Pin the surface with
    :func:`tests.automation_harness.assert_field_sweep_map`.

    *Physical-layer only* — it reads each field trajectory, never writes it back
    into ``Design`` (the Three-Layer Law).  ``directions``/``intensities_pN`` are
    user/spec inputs; the cells measure magnitudes (τ, alignment projection, bp
    retention) → direction-agnostic, no sign/handedness reasoning here.
    """
    parent = specimen["job"]
    if parent.status != OxdnaStatus.completed:
        raise ValueError(
            "sweep_field_response: the specimen's relaxed parent job is not "
            f"completed (status={parent.status}); build it with build_field_specimen")
    design = specimen["design"]
    anchor = specimen["anchor"]
    anchor_keys = specimen["anchor_keys"]
    dirs = [tuple(float(c) for c in d) for d in directions]
    intensities = [float(p) for p in intensities_pN]

    response: dict[tuple, dict] = {}
    skipped: list[tuple] = []
    for pN in intensities:
        for d in dirs:
            info = append_field(parent.job_id, workspace, field_pN=pN, dir=list(d),
                                anchors=[anchor], steps=field_steps,
                                anchor_stiff=anchor_stiff)
            job = wait_for_terminal(info["job_id"], workspace, timeout=timeout)
            cell = _measure_field_cell(job, workspace, design, list(d), anchor_keys,
                                       melt_floor=melt_floor,
                                       min_confidence=min_confidence)
            if cell is None:
                skipped.append((pN, d))
                continue
            response[(pN, d)] = cell
    return {"map": response, "skipped": skipped, "intensities_pN": intensities,
            "directions": dirs, "melt_floor": melt_floor}


# ── CAPSTONE: cross-design automated field-response campaign (AF-23) ────────────

def run_field_campaign(specimens, intensities_pN, directions, workspace, *,
                       field_steps: int = 2000, melt_floor: float = 0.5,
                       min_confidence: int = 10, timeout: float = 30.0,
                       anchor_stiff: float = DEFAULT_ANCHOR_STIFF,
                       **relax_params) -> dict:
    """Run the SAME ``(|E|, direction)`` field sweep across MANY designs and assemble
    a per-design response-surface campaign (AF-23, Tier 6 capstone — the user's stated
    goal: *automatic exploration of which E-field intensities × directions align which
    DNA structures, on what equilibration timescale, without ripping them apart, for
    various designs*).

    ``specimens`` is a list of dicts, one per design::

        {"name": "6hb", "design": <Design | build-spec dict>,
         "anchor": {"kind": "overhang", "id": …},
         "overhang": {…} | None, "sequence": True | False}

    For each entry this composes the de-risked batch path: :func:`build_field_specimen`
    (build → optional overhang → sequence → relax → resolve the field anchor) followed
    by :func:`sweep_field_response` (a child field job per ``(|E|, direction)`` cell off
    that specimen's relaxed parent).  Each design runs in its own ``workspace/campaign/
    <name>`` subdir so the per-design job trees never collide.

    Returns ``{"sweeps": {name: sweep_dict}, "skipped": [(name, reason), …],
    "names": [name, …], "intensities_pN": [...], "directions": [...],
    "melt_floor": …}``.  A design whose build or sweep raises is recorded in
    ``skipped`` (NOT silently dropped — the campaign stays auditable, mirroring
    :func:`sweep_field_response`'s per-cell skip list).  Pin the campaign with
    :func:`tests.automation_harness.assert_field_campaign`.

    The ``directions``/``intensities_pN`` grid is shared across designs so their
    response surfaces are directly comparable (the cross-design distinguishability the
    capstone proves).  *Physical-layer only* — it reads each field trajectory, never
    writes it back into ``Design`` (the Three-Layer Law).  Field direction + magnitude
    are spec inputs; the cells measure magnitudes (τ, alignment, bp retention) →
    direction-agnostic, no sign/handedness reasoning here.  Transparently swaps to the
    AF-21/22 oxpy fast path once that ships (same specimen + sweep contract).
    """
    ws_root = Path(workspace)
    dirs = [tuple(float(c) for c in d) for d in directions]
    intensities = [float(p) for p in intensities_pN]

    sweeps: dict[str, dict] = {}
    skipped: list[tuple] = []
    names: list[str] = []
    for i, entry in enumerate(specimens):
        name = str(entry.get("name") or f"design_{i}")
        names.append(name)
        safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in name)
        sub = ws_root / "campaign" / f"{i:03d}_{safe}"
        sub.mkdir(parents=True, exist_ok=True)
        try:
            specimen = build_field_specimen(
                entry["design"], sub, anchor=entry["anchor"],
                overhang=entry.get("overhang"), sequence=entry.get("sequence", True),
                timeout=timeout, **relax_params)
            sweep = sweep_field_response(
                specimen, intensities, dirs, sub, field_steps=field_steps,
                melt_floor=melt_floor, min_confidence=min_confidence,
                timeout=timeout, anchor_stiff=anchor_stiff)
        except Exception as exc:  # noqa: BLE001 — recorded, not swallowed (oracle gates)
            skipped.append((name, f"{type(exc).__name__}: {exc}"))
            continue
        sweeps[name] = sweep
    return {"sweeps": sweeps, "skipped": skipped, "names": names,
            "intensities_pN": intensities, "directions": dirs,
            "melt_floor": melt_floor}


# ── Hardware benchmark: auto-tune the relaxation backend headlessly ────────────

def run_oxdna_benchmark(design: Design, workspace, *, steps: int | None = None,
                        configs=None, runner=None) -> dict:
    """Headless oxDNA hardware benchmark: build a size-matched synthetic proxy, sweep
    the candidate hardware configs, and return the result dict (carries
    ``recommendation`` ``{backend, device, steps_per_s, …}``).

    Drives the REAL trial orchestration (``benchmark_runner.run_oxdna_trials`` — the
    same sweep the ``POST /benchmark/oxdna`` route runs in a background thread) inline,
    so a script / AI builder can auto-tune *this* machine without a browser.  The proxy
    is a sequenced 6hb sized ≈ the design's nucleotide count (never the real design —
    avoids solvating a huge structure), so even an empty design yields a valid sweep.

    ``configs`` defaults to the real per-machine grid (CPU + one CUDA trial per visible
    device); pass an explicit list to sweep a fixed grid.  ``runner`` is the injectable
    launcher seam (``run_oxdna_trials``'s ``runner=``) so a test sweeps with a stub and
    no GPU.  ``steps`` overrides the per-trial step count.  Requires ``find_oxdna()`` to
    resolve a binary (``$OXDNA_BIN``) unless a ``runner`` is injected that needs none.

    Feed ``result["recommendation"]`` to :func:`apply_oxdna_benchmark` to persist it in
    a design, then :func:`run_relaxation_tuned` to relax on the discovered backend.
    """
    from backend.core import benchmark as bench
    from backend.core import benchmark_runner as br
    from backend.core import hardware
    from backend.core.design_geometry import _geometry_for_design
    from backend.physics.oxdna_interface import _strand_nucleotide_order

    n_target = len(_strand_nucleotide_order(design))
    syn, plan = br.build_synthetic_design(n_target, max_nt=bench.OXDNA_MAX_NT)
    geometry = _geometry_for_design(syn)
    if configs is None:
        configs = bench.oxdna_config_grid(hardware.enumerate_cuda_devices())

    state = br.BenchmarkState(
        benchmark_id=br.new_benchmark_id(),
        engine="oxdna",
        trials_total=len(configs),
        proxy_nucleotides=plan["proxy_nucleotides"],
        requested_nucleotides=plan["requested_nucleotides"],
        note=bench.extrapolate_note(
            plan["proxy_nucleotides"], plan["requested_nucleotides"], capped=plan["capped"]),
    )
    # A dedicated subdir — ``run_oxdna_trials`` rmtree's its workdir on exit, so it must
    # NOT be the bare workspace (that would wipe a sibling relaxation's job dir).
    workdir = Path(workspace) / "benchmark_runs" / state.benchmark_id
    kw = {} if steps is None else {"steps": steps}
    asyncio.run(br.run_oxdna_trials(state, syn, geometry, configs, workdir,
                                    runner=runner, **kw))
    return state.to_dict()


def apply_oxdna_benchmark(design: Design, recommendation: dict, *,
                          hostname: str | None = None) -> Design:
    """Write an oxDNA benchmark ``recommendation`` into a COPY of ``design`` under
    ``metadata.hardware_defaults[hostname]`` and return it (the original is untouched).

    Mirrors ``POST /benchmark/{id}/apply`` but on a passed design rather than the active
    session state, so a headless tuner can persist the discovered config and then relax
    with it.  ``hostname`` defaults to this machine's name (``hardware.hostname()``) —
    the key :func:`run_relaxation_tuned` reads back.  Preserves any existing NAMD slot
    for the host.
    """
    from backend.core import hardware
    from backend.core.models import HardwareBenchmark, OxdnaHardwareDefault

    host = hostname or hardware.hostname()
    out = design.model_copy(deep=True)
    slot = out.metadata.hardware_defaults.get(host) or HardwareBenchmark()
    slot.oxdna = OxdnaHardwareDefault(
        backend=recommendation["backend"],
        device=recommendation.get("device", "0"),
        steps_per_s=recommendation.get("steps_per_s"),
        proxy_nucleotides=recommendation.get("proxy_nucleotides"),
    )
    out.metadata.hardware_defaults[host] = slot
    return out


def run_relaxation_tuned(design: Design, workspace, *, hostname: str | None = None,
                         timeout: float = 30.0, **params) -> OxdnaJob:
    """One-call headless relaxation that HONOURS the design's benchmarked hardware
    default: resolve ``metadata.hardware_defaults[hostname]`` → ``{backend, device}``
    (:func:`benchmark.resolve_oxdna_relax_config`) and feed it to :func:`run_relaxation`,
    so the run uses the fastest config the Benchmark discovered on this machine — and a
    portable ``CPU`` run when none was benchmarked.

    This is the bridge AF-13 P4's iterate-until-met loop uses to relax on the fastest
    discovered backend instead of a hard-coded CPU default.  Explicit ``backend`` /
    ``device`` in ``params`` override the resolved values; everything else forwards to
    :func:`create_job` (``mc_steps`` / ``md_relax_steps`` / ``equil_steps`` /
    ``min_bp_retained`` / …).
    """
    from backend.core import benchmark as bench
    from backend.core import hardware

    host = hostname or hardware.hostname()
    cfg = bench.resolve_oxdna_relax_config(design.metadata.hardware_defaults.get(host))
    for key in ("backend", "device"):
        if key in params:
            cfg[key] = params.pop(key)
    return run_relaxation(design, workspace, timeout=timeout,
                          backend=cfg["backend"], device=cfg["device"], **params)


# ── Constraint-driven design: the iterate-until-met loop (AF-13 Phase 4) ───────

def _pool_until_conclusive(job, workspace, parsed_constraint, *, production_steps,
                           max_production_rounds, timeout):
    """Append production runs to ``job`` (pooling more frames each round) until the
    constraint verdict is conclusive (``met``/``unmet``) or the round budget is
    exhausted.  Returns ``(verdict, n_rounds)``.

    The flexibility-map route pools EVERY production stage's frames, so each extra
    round raises the pooled-frame count toward ``min_confidence`` — this is the
    concrete "run a longer production" response to an ``inconclusive`` verdict.
    """
    from backend.core.oxdna_health import check_relaxed_constraint

    verdict = None
    for r in range(1, max_production_rounds + 1):
        append_production(job.job_id, workspace, steps=production_steps)
        wait_for_terminal(job.job_id, workspace, timeout=timeout)
        rmsf = read_flexibility_map(job.job_id, workspace)
        verdict = check_relaxed_constraint(parsed_constraint, rmsf)
        if verdict["status"] != "inconclusive":
            return verdict, r
    return verdict, max_production_rounds


def iterate_to_constraint(build_fn, adjust_fn, constraint, workspace, *,
                          initial_knob, max_iterations: int = 8,
                          production_steps: int = 6000,
                          max_production_rounds: int = 8, timeout: float = 30.0,
                          tuned: bool = False, **relax_params) -> dict:
    """Closed **build → relax → measure → adjust** loop that drives a parametric
    design knob until a relaxed-structure constraint is met (AF-13 Phase 4 — the
    capstone of the physical-layer tier).

    Each outer iteration:

    1. ``build_fn(knob)`` edits **topology** (the knob — e.g. a bend curvature via
       :func:`headless_build.add_bend`, a loop/skip count, a length) and returns a
       fully-sequenced :class:`~backend.core.models.Design`;
    2. it is relaxed headlessly (:func:`run_relaxation`, or
       :func:`run_relaxation_tuned` when ``tuned=True`` — relax on the machine's
       benchmarked backend) and a production run is appended;
    3. the **production mean structure** is read (:func:`read_flexibility_map`) and
       the constraint is REPORTED on it via
       :func:`~backend.core.oxdna_health.check_relaxed_constraint`;
    4. the loop branches on the verdict **status** (never the raw measured value —
       the load-bearing AF-13 P3 confidence gate):

       - ``met``          → return ``{"status": "met", ...}`` immediately;
       - ``unmet``        → ``adjust_fn(knob, verdict)`` picks the next knob, rebuild;
       - ``inconclusive`` → too few frames pooled; append MORE production to the
         SAME job (:func:`_pool_until_conclusive`) until conclusive or the round
         budget runs out — a longer production, NOT a knob change.  If it stays
         inconclusive after ``max_production_rounds`` the loop stops (it cannot
         certify a verdict, so it must not blindly adjust the knob).

    ``adjust_fn(knob, verdict) -> next_knob`` is the caller's domain knowledge of
    how the knob maps to the measure (e.g. bisection on curvature); the driver is
    deliberately measure-agnostic.  ``constraint`` is a raw AF-13 P3 spec (validated
    once up-front via :func:`~backend.core.oxdna_health.parse_constraint_spec`, so a
    malformed constraint fails before any expensive run).

    Returns ``{status, knob, job, iterations, verdict}`` where ``status`` is
    ``"met"`` or ``"exhausted"``, ``iterations`` is the per-attempt history
    (``{knob, verdict, job_id, production_rounds}``), and ``verdict`` is the final
    verdict dict.

    **Three-Layer Law (load-bearing).** The knob varies *topology*; geometry is
    re-derived; physics is relaxed; the measurement is *read* from the relaxed mean
    structure.  The relaxed coordinates are **never written back into ``Design``** —
    only the scalar verdict steers the next topology edit.  Composes already-covered
    wrappers (wraps no new route), so the oxDNA coverage count is unchanged.
    """
    from backend.core.oxdna_health import parse_constraint_spec

    parsed = parse_constraint_spec(constraint)
    relax = run_relaxation_tuned if tuned else run_relaxation
    knob = initial_knob
    history: list[dict] = []
    job = None
    for _ in range(max_iterations):
        design = build_fn(knob)
        job = relax(design, workspace, timeout=timeout, **relax_params)
        if job.status != OxdnaStatus.completed:
            history.append({"knob": knob, "verdict": None, "job_id": job.job_id,
                            "production_rounds": 0, "error": job.error})
            break
        verdict, rounds = _pool_until_conclusive(
            job, workspace, parsed, production_steps=production_steps,
            max_production_rounds=max_production_rounds, timeout=timeout)
        history.append({"knob": knob, "verdict": verdict, "job_id": job.job_id,
                        "production_rounds": rounds})
        status = verdict["status"] if verdict else "inconclusive"
        if status == "met":
            return {"status": "met", "knob": knob, "job": job,
                    "iterations": history, "verdict": verdict}
        if status == "inconclusive":
            break  # could not gather enough confidence — cannot steer the knob
        knob = adjust_fn(knob, verdict)  # unmet → move the knob and rebuild
    return {"status": "exhausted", "knob": knob, "job": job,
            "iterations": history,
            "verdict": history[-1]["verdict"] if history else None}
