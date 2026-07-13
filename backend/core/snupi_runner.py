"""
SNUPI FEM Runner — background execution of a single SNUPI shape prediction.

Sibling of ``cando_runner.py``, predict-only: a SNUPI job is a PURE in-process
Python solve (``backend.physics.fem_solver.predict_shape`` with ``material="snupi"``),
not an external simulator.  There is no subprocess, no GPU, and no availability probe —
only the two solver modes (linear "Coarse" preview vs nonlinear "Fine" solve).

The runner:

  1. prepare: write a self-contained ``design.json`` snapshot into the job dir, so
     the solve (and every display read) is decoupled from live editor state.
  2. run ``predict_shape(..., material=job.material)`` on the snapshot in a background
     daemon thread (the fine solve is ~1 min; the thread keeps the sidebar polling).
  3. cache the deformed positions as ``display.json`` and the per-bp RMSF as ``rmsf.json``.
  4. mark the job completed.

Stopping is best-effort: ``predict_shape`` is a monolithic scipy solve that can't be
interrupted mid-way, so stop sets a cancel flag; a running solve finishes, then the
thread discards the result and marks the job stopped instead of caching.

FEM output is Physical-layer only — never written back into Design topology.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from backend.core.models import Design
from backend.core.snupi_job import SnupiJob, SnupiStatus

logger = logging.getLogger(__name__)


# ── Global task registry ──────────────────────────────────────────────────────

@dataclass
class _RunningHandle:
    thread:    threading.Thread
    cancelled: bool = False


_RUNNING: dict[str, _RunningHandle] = {}


def is_running(job_id: str) -> bool:
    handle = _RUNNING.get(job_id)
    return handle is not None and handle.thread.is_alive()


# ── Prepare: write the self-contained job dir ─────────────────────────────────

def prepare_snupi_job(design: Design, job: SnupiJob, workspace_dir: Path) -> None:
    """Write a self-contained ``design.json`` snapshot into the job dir, so the
    solve (and every display read) is decoupled from live editor state."""
    jd = job.job_dir(workspace_dir)
    jd.mkdir(parents=True, exist_ok=True)
    (jd / "design.json").write_text(design.model_dump_json())


def _load_snapshot_design(job_dir: Path) -> Optional[Design]:
    snap = job_dir / "design.json"
    if not snap.exists():
        return None
    try:
        return Design.model_validate_json(snap.read_text())
    except Exception:  # noqa: BLE001
        return None


# ── Cache accessors ───────────────────────────────────────────────────────────

def load_cached(job_dir: Path, name: str) -> Optional[dict]:
    """Load a cached ``display.json`` / ``rmsf.json`` payload, or None."""
    p = job_dir / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return None


def load_display(job_dir: Path) -> Optional[dict]:
    """The cached predicted positions payload (applyFemPositions list), or None."""
    return load_cached(job_dir, "display.json")


def load_rmsf(job_dir: Path) -> Optional[dict]:
    """The cached per-bp RMSF payload, or None."""
    return load_cached(job_dir, "rmsf.json")


def load_trajectory(job_dir: Path) -> Optional[dict]:
    """The cached dynamics trajectory ({keys, frames, n_frames}) for the animation toggle, or None."""
    return load_cached(job_dir, "trajectory.json")


# ── Progress (time-based estimate; the true completion signal is the thread) ──

def _estimate_seconds(job: SnupiJob) -> float:
    """Rough wall-clock estimate for the solve, scaled by system size + mode.

    Only drives the progress bar (capped < 1.0 until the thread ends); the true
    completion signal is the runner thread finishing.  Reference: a 6HB/210
    (~1260 duplex nodes) nonlinear static solve ≈ 60 s; the linear preview ≈ a few s.

    **Langevin dynamics** (``job.dynamics``) is a different beast: a fixed 60 000-step GJF
    trajectory, NOT the ~20-step static solve — so the static estimate under-shoots by ~10×
    and pins the bar at its 0.97 cap in seconds.  Full **RPY hydrodynamics** adds a dense
    O((6N)³) friction factorisation plus a dense (6N)² basis transform every step, which
    DOMINATES at scale (an ~880-node / 60k-step run ≈ 650 s here).  RPY wall-clock is also
    very CPU-contention-sensitive, so this is an order-of-magnitude figure — deliberately on
    the generous side so ``overall = elapsed/est`` keeps climbing rather than pinning early.
    """
    nodes = max(1.0, job.n_nucleotides / 2.0)          # ≈ base pairs ≈ FEM nodes

    if getattr(job, "dynamics", False):
        # predict_shape runs a fixed dynamics_steps=60000 GJF trajectory (see fem_solver).
        step_scale = 60000.0 / 60000.0
        # Langevin base (diagonal Stokes): a sparse K·q per step (O(nodes)) + one generalised
        # eigsh for dt auto-sizing.  ~10 s at 630 nodes / 60k steps.
        est = 5.0 + (nodes / 630.0) * step_scale * 10.0
        if getattr(job, "hydrodynamics", False):
            # RPY dense friction inverse+eigendecomposition + a dense (6N)² transform per step.
            # Calibrated to an 882-node / 60k-step run ≈ 650 s (grows ∝ nodes²).
            est += (nodes / 882.0) ** 2 * step_scale * 650.0
        return max(2.0, est)

    if job.nonlinear:
        est = 3.0 + (nodes / 1260.0) * (job.n_steps / 20.0) * 55.0
    else:
        est = 1.0 + (nodes / 1260.0) * 4.0
    if job.with_rmsf:
        est += (nodes / 1260.0) * 8.0                  # the 200-mode NMA eigensolve
    return max(2.0, est)


def job_progress(job: SnupiJob, workspace_dir: Path) -> dict:
    """Overall progress fraction + ETA for the panel."""
    stage = job.stages[0] if job.stages else None
    overall = 0.0
    eta_seconds: float | None = None
    if job.status == SnupiStatus.completed:
        overall = 1.0
    elif job.status in (SnupiStatus.failed, SnupiStatus.stopped):
        overall = 0.0
    elif job.status == SnupiStatus.running and stage and stage.started_at:
        elapsed = time.time() - stage.started_at
        est = _estimate_seconds(job)
        overall = min(0.97, elapsed / est)
        eta_seconds = max(0.0, est - elapsed)
    return {
        "overall":      overall,
        "status":       job.status.value,
        "stage_status": stage.status if stage else None,
        "eta_seconds":  eta_seconds,
        "sim_seconds":  job.sim_seconds,
    }


# ── Execution ─────────────────────────────────────────────────────────────────

class _Cancelled(Exception):
    pass


def _cache_fem_analysis(job: SnupiJob, jd: Path, result: dict) -> None:
    """Write a ``predict_shape`` result to the job's ``display.json`` + ``rmsf.json`` and record the
    node/RMSF summary on the job — the display cache every SNUPI display mode reads (deform / flex /
    deviation / cylinders)."""
    positions = result.get("positions", [])
    (jd / "display.json").write_text(json.dumps({
        "solver":    result.get("solver"),
        "positions": positions,
        "axis":      result.get("axis", []),   # per-bp helix-centre nodes (cylinder rep)
    }))
    traj = result.get("trajectory")
    if traj and traj.get("n_frames"):
        # The thermal/reconfiguration trajectory for the animation toggle (dynamics jobs only).
        (jd / "trajectory.json").write_text(json.dumps(traj))
    rmsf = result.get("rmsf")
    rmsf_min = rmsf_max = None
    if rmsf:
        (jd / "rmsf.json").write_text(json.dumps({"rmsf": rmsf}))
        vals = [r["rmsf_nm"] for r in rmsf]
        if vals:
            rmsf_min, rmsf_max = min(vals), max(vals)
    # positions carry two entries (FORWARD/REVERSE) per axis node; the RMSF list is one entry per
    # node, so it is the honest FEM-node (= base pair) count.
    job.n_nodes = len(rmsf) if rmsf else (len(positions) // 2 if positions else 0)
    job.rmsf_min_nm = round(rmsf_min, 3) if rmsf_min is not None else None
    job.rmsf_max_nm = round(rmsf_max, 3) if rmsf_max is not None else None


def _run_job(job: SnupiJob, workspace_dir: Path) -> None:
    """Thread body: load the snapshot, run predict_shape (SNUPI material), extract + cache."""
    jd = job.job_dir(workspace_dir)
    handle = _RUNNING.get(job.job_id)

    def _cancelled() -> bool:
        return handle is not None and handle.cancelled

    try:
        design = _load_snapshot_design(jd)
        if design is None:
            raise RuntimeError("job design snapshot (design.json) missing")

        from backend.physics.fem_solver import predict_shape

        if _cancelled():
            raise _Cancelled()

        # Flip the JOB status to running (not just the stage) so the panel's progress bar +
        # ETA — both gated on status==running — light up during the solve.
        job.status = SnupiStatus.running
        job.stages[0].status = "running"
        job.stages[0].started_at = time.time()
        job.save(workspace_dir)

        t0 = time.monotonic()
        result = predict_shape(
            design,
            nonlinear = job.nonlinear,
            n_steps   = job.n_steps,
            with_rmsf = job.with_rmsf,
            # The SNUPI delta: anisotropic per-motif 6×6 material + twist–stretch couplings +
            # compliant crossover beams (material="snupi").  A job may instead select the
            # isotropic "cando" baseline for an in-tab A/B comparison.
            material  = getattr(job, "material", "snupi"),
            # G12: MgCl₂ molarity → Debye length of the SNUPI inter-helix electrostatics
            # (snupi-only; ignored by cando). Default 0.02 = SNUPI's 20 mM buffer.
            mgcl2_M   = getattr(job, "mgcl2_M", 0.02),
            # Langevin structural dynamics: run a thermal trajectory and report its time-mean shape +
            # trajectory RMSF (same display payload). hydrodynamics=True → full RPY coupled friction.
            dynamics      = getattr(job, "dynamics", False),
            hydrodynamics = getattr(job, "hydrodynamics", False),
            # Anchors (Dirichlet BC) + uniform E-field body load — job-request annotations, never a
            # topology edit (C1/C2).  A field needs ≥1 anchor to hold against (COM drift);
            # predict_shape falls back to the free centroid-pinned solve if a selection resolves
            # to nothing.
            anchors   = getattr(job, "anchors", None),
            field     = getattr(job, "field", None),
        )
        sim_seconds = time.monotonic() - t0

        if _cancelled():
            raise _Cancelled()

        _cache_fem_analysis(job, jd, result)
        job.sim_seconds = round(sim_seconds, 2)
        for st in job.stages:
            st.status = "done"
        job.status = SnupiStatus.completed
        job.error = None
        job.save(workspace_dir)
        logger.info("snupi job %s completed in %.1fs (%s solve, material=%s, %s nodes)",
                    job.job_id, sim_seconds, result.get("solver"),
                    getattr(job, "material", "snupi"), job.n_nodes)

    except _Cancelled:
        job.status = SnupiStatus.stopped
        for st in job.stages:
            if st.status != "done":
                st.status = "failed"
        job.save(workspace_dir)
    except Exception as exc:  # noqa: BLE001
        logger.error("snupi job %s failed: %s", job.job_id, exc, exc_info=True)
        if _cancelled():
            job.status = SnupiStatus.stopped
        else:
            job.status = SnupiStatus.failed
            job.error = str(exc)
        for st in job.stages:
            if st.status != "done":
                st.status = "failed"
        job.save(workspace_dir)
    finally:
        _RUNNING.pop(job.job_id, None)


def start_job(job: SnupiJob, workspace_dir: Path) -> None:
    """Launch the job's runner in a background daemon thread. Idempotent if running."""
    if is_running(job.job_id):
        return
    handle = _RunningHandle(thread=threading.Thread(
        target=_run_job, args=(job, workspace_dir),
        name=f"snupi-runner-{job.job_id}", daemon=True))
    _RUNNING[job.job_id] = handle
    handle.thread.start()


def stop_job(job_id: str, workspace_dir: Path) -> bool:
    """Stop a running SNUPI job.  Sets the cancel flag; a running scipy solve can't be
    interrupted mid-way, so the flagged thread finishes the current solve, then discards
    the result and marks the job stopped.  If no thread is alive, marks a stray
    ``running`` job stopped directly.  Returns True if a live job was found."""
    handle = _RUNNING.get(job_id)
    live = handle is not None and handle.thread.is_alive()
    if handle is not None:
        handle.cancelled = True
    if not live:
        try:
            job = SnupiJob.load(job_id, workspace_dir)
        except Exception:  # noqa: BLE001
            return False
        if job.status == SnupiStatus.running:
            job.status = SnupiStatus.stopped
            for st in job.stages:
                if st.status != "done":
                    st.status = "failed"
            job.save(workspace_dir)
    return live


def reconcile_snupi_status(job: SnupiJob, workspace_dir: Path) -> SnupiJob:
    """Recover a detached job's status after the runner thread died (e.g. a
    ``uvicorn --reload`` restart mid-solve).  If the cached ``display.json`` exists the
    solve finished → ``completed``; otherwise the thread died without caching → ``stopped``.
    No-op unless the job is an orphaned ``running`` one."""
    if job.status != SnupiStatus.running:
        return job
    if is_running(job.job_id):
        return job
    jd = job.job_dir(workspace_dir)
    if (jd / "display.json").exists():
        job.status = SnupiStatus.completed
        for st in job.stages:
            st.status = "done"
        job.save(workspace_dir)
        return job
    job.status = SnupiStatus.stopped
    for st in job.stages:
        if st.status != "done":
            st.status = "failed"
    job.save(workspace_dir)
    return job
