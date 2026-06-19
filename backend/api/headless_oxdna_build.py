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
