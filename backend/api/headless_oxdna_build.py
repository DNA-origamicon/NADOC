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
    start_oxdna_job as _route_start_job,
)
from backend.core.models import Design
from backend.core.oxdna_job import OxdnaJob, OxdnaStatus
from backend.physics.oxdna_interface import DEFAULT_ANCHOR_STIFF

_scratch_counter = itertools.count()

_TERMINAL = (OxdnaStatus.completed, OxdnaStatus.failed, OxdnaStatus.stopped)


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
    design_source_path: str | None = None,
) -> dict:
    """Create + prepare a 3-stage relaxation job from ``design`` (mirrors
    ``POST /oxdna/jobs``).  Returns the job dict; read ``["job_id"]``.

    Drives the real ``create_oxdna_job`` handler — the same staging the Dynamics
    panel triggers.  ``min_bp_retained`` defaults to ``0.0`` because the mock binary
    does not actually relax (it copies the input conf), so the base-pair-retention
    gate must be off for headless orchestration tests; a real GPU run should raise
    it back to ~0.5.  Requires ``find_oxdna()`` to resolve a binary (set
    ``$OXDNA_BIN``), and ``design`` to be fully sequenced (oxDNA rejects undefined
    bases).
    """
    body = CreateOxdnaJobRequest(
        backend=backend,
        device=device,
        salt_concentration=salt_concentration,
        mc_steps=mc_steps,
        md_relax_steps=md_relax_steps,
        equil_steps=equil_steps,
        min_bp_retained=min_bp_retained,
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
    with _use_workspace(workspace):
        return asyncio.run(
            _route_append_production(job_id, ProductionRequest(steps=steps))
        )


def append_field(job_id: str, workspace, *, field_pN: float, dir, anchors: list[dict],
                 steps: int = 2000, anchor_stiff: float = DEFAULT_ANCHOR_STIFF) -> dict:
    """Append an electric-field stage to a completed job (mirrors
    ``POST /oxdna/jobs/{id}/field``).  ``anchors`` are descriptors resolved to
    pinned nucleotides (e.g. ``{'kind':'domain','strand_id':…,'domain_index':0}``
    or ``{'kind':'overhang','id':…}``)."""
    with _use_workspace(workspace):
        return asyncio.run(_route_append_field(job_id, FieldRequest(
            field_pN=field_pN, dir=list(dir), anchors=anchors,
            steps=steps, anchor_stiff=anchor_stiff)))


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
