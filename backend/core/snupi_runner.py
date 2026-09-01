"""
SNUPI FEM Runner — background execution of a single SNUPI shape prediction.

Sibling of ``cando_runner.py``, predict-only: a SNUPI job is a pure Python FEM solve
(``backend.physics.fem_solver.predict_shape`` with ``material="snupi"``), not an external
simulator — the two "engines" are the solver modes (linear "Coarse" preview vs nonlinear
"Fine" solve).  There is no GPU and no availability probe.

The solve runs in a DETACHED worker subprocess (:mod:`backend.core.snupi_worker`), NOT an
in-process daemon thread.  The reason is operational: a "Fine" solve on a large design (e.g.
VoltronCore, ~7 000 FEM nodes) legitimately takes 5–7 min, and the dev server runs under
``uvicorn --reload``.  A daemon thread lives *inside* that server process, so any reload
(a save under ``backend/`` or ``scripts/`` — including a concurrent editor — or a manual
restart) during the multi-minute solve killed the thread and left the job stranded as
``stopped`` ("stops on its own").  The worker is launched with ``start_new_session=True``,
giving it its own process group/session, so the reloader (which signals only the server's
group) no longer reaches it; it finishes and writes its result, which the restarted server
picks up via :func:`reconcile_snupi_status`.

The runner:

  1. prepare: write a self-contained ``design.json`` snapshot into the job dir, so
     the solve (and every display read) is decoupled from live editor state.
  2. ``start_job``: spawn the detached worker, which runs ``predict_shape(..., material=
     job.material)`` on the snapshot (see :func:`solve_and_cache`).
  3. cache the deformed positions as ``display.json`` and the per-bp RMSF as ``rmsf.json``.
  4. the worker marks the job completed (or failed); ``reconcile`` recovers an orphan.

Stopping is now immediate: ``stop_job`` sends SIGTERM→SIGKILL to the detached worker, so a
running solve dies at once instead of running to completion first.

FEM output is Physical-layer only — never written back into Design topology.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from backend.core.models import Design
from backend.core.snupi_job import SnupiJob, SnupiStatus

logger = logging.getLogger(__name__)

# Repo root — the cwd the detached solve worker is launched from, so ``python -m
# backend.core.snupi_worker`` resolves the ``backend`` package.  This file is
# backend/core/snupi_runner.py, so parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Detached-worker registry ──────────────────────────────────────────────────
# The solve runs in a DETACHED subprocess (its own session via ``start_new_session``),
# NOT an in-process daemon thread — so a ``uvicorn --reload`` restart mid-solve no longer
# kills it (the reloader signals only the server's own process group).  Liveness is the
# worker PID persisted on the job (``job.pid``), which survives the restart; this
# in-process map is only a fast path + a zombie reaper for children started HERE.

_STARTED: dict[str, int] = {}


def _pid_alive(pid: Optional[int]) -> bool:
    """True if ``pid`` names a live process we could signal (``os.kill(pid, 0)``)."""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by another user — shouldn't happen here
    return True


def is_running(job_id: str, workspace_dir: Optional[Path] = None) -> bool:
    """True while the detached solve worker for ``job_id`` is alive.

    Authoritative source is the job's persisted status + pid (survives a server reload);
    without a workspace the in-process ``_STARTED`` map is the fallback (legacy callers).
    """
    if workspace_dir is not None:
        try:
            job = SnupiJob.load(job_id, workspace_dir)
        except Exception:  # noqa: BLE001
            job = None
        if job is not None:
            if job.status != SnupiStatus.running:
                return False
            return _pid_alive(job.pid)
    return _pid_alive(_STARTED.get(job_id))


def _kill_pid(pid: int) -> None:
    """SIGTERM→SIGKILL the worker.  A ``start_new_session`` child is its own group leader
    (pgid == pid), so we group-kill it (and anything it spawned); otherwise signal just it."""
    try:
        pgid = os.getpgid(pid)
    except OSError:
        return
    group = pgid == pid
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig) if group else os.kill(pid, sig)
        except OSError:
            return
        for _ in range(20):  # ≤1 s grace before escalating to SIGKILL
            if not _pid_alive(pid):
                return
            time.sleep(0.05)


# ── Prepare: write the self-contained job dir ─────────────────────────────────


def prepare_snupi_job(design: Design, job: SnupiJob, workspace_dir: Path) -> None:
    """Write a self-contained ``design.json`` snapshot into the job dir, so the
    solve (and every display read) is decoupled from live editor state."""
    design = design.without_reference_geometry()
    jd = job.job_dir(workspace_dir)
    jd.mkdir(parents=True, exist_ok=True)
    (jd / "design.json").write_text(design.model_dump_json())


def _load_snapshot_design(job_dir: Path) -> Optional[Design]:
    snap = job_dir / "design.json"
    if not snap.exists():
        return None
    try:
        return Design.from_json(snap.read_text())
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


def load_display_bin(job_dir: Path) -> Optional[bytes]:
    """Load the compact static FEM sidecar, deriving it once for older jobs."""
    path = job_dir / "display.bin"
    if path.exists():
        try:
            return path.read_bytes()
        except OSError:
            return None
    display = load_display(job_dir)
    if not display or not display.get("positions"):
        return None
    from backend.core.cando_runner import pack_static_fem_frame_bin

    payload = pack_static_fem_frame_bin(display, solver=display.get("solver"))
    path.write_bytes(payload)
    return payload


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
    nodes = max(1.0, job.n_nucleotides / 2.0)  # ≈ base pairs ≈ FEM nodes

    if getattr(job, "dynamics", False):
        # predict_shape runs a fixed dynamics_steps=60000 GJF trajectory (see fem_solver).
        step_scale = 60000.0 / 60000.0
        # Langevin base (diagonal Stokes): a sparse K·q per step (O(nodes)) + one generalised
        # eigsh for dt auto-sizing.  ~10 s at 630 nodes / 60k steps.
        est = 5.0 + (nodes / 630.0) * step_scale * 10.0
        if getattr(job, "tails", False):
            # Free-ssDNA tails add a second force evaluation per step (the batched corotational
            # chain kernel). Measured on VoltronCore: ~2.1× the per-step cost of the core alone.
            est *= 2.1
        if getattr(job, "hydrodynamics", False):
            coarse = getattr(job, "hydro_coarse_bp", None)
            if coarse:
                # COARSE blob RPY: the dense object is 6B×6B for B = nodes/k blobs, not 6N×6N — so the
                # cost falls as (nodes/k)², NOT nodes². Using the dense law here would over-estimate a
                # full M13 coarse run by ~60×, and the bar would crawl. Calibrated on the k=8 / 7240-node
                # M13 run: ~14.5 ms per step of friction work at B=920 ⇒ ~900 s per 60k steps.
                blobs = max(1.0, nodes / float(coarse))
                est += (blobs / 920.0) ** 2 * step_scale * 900.0
            else:
                # EXACT RPY: dense friction inverse + eigendecomposition + a dense (6N)² transform per
                # step. Calibrated to an 882-node / 60k-step run ≈ 650 s (grows ∝ nodes²).
                est += (nodes / 882.0) ** 2 * step_scale * 650.0
        return max(2.0, est)

    if job.nonlinear:
        est = 3.0 + (nodes / 1260.0) * (job.n_steps / 20.0) * 55.0
    else:
        est = 1.0 + (nodes / 1260.0) * 4.0
    if job.with_rmsf:
        est += (nodes / 1260.0) * 8.0  # the 200-mode NMA eigensolve
    return max(2.0, est)


PROGRESS_FILE = "progress.json"


def write_progress(
    job_dir: Path, fraction: float, phase: str, info: dict | None = None
) -> None:
    """Publish REAL solve progress from the (detached) worker to the job dir.

    Written atomically — the server polls this file while the worker is mid-solve, and a torn read
    would show a nonsense percentage. ``info`` carries the fine detail (step / n_steps / dt / node +
    blob counts / divergence-retry attempt) so a long run can be inspected while it runs rather than
    only post-mortem. Best-effort: a progress-write failure must never kill a solve that has already
    burned minutes of CPU."""
    try:
        tmp = job_dir / (PROGRESS_FILE + ".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "fraction": max(0.0, min(1.0, float(fraction))),
                    "phase": phase,
                    "at": time.time(),
                    **(info or {}),
                }
            )
        )
        tmp.replace(job_dir / PROGRESS_FILE)
    except Exception:  # pragma: no cover — best-effort
        pass


def log_worker(job_dir: Path, message: str) -> None:
    """Append a timestamped line to the job's ``worker.log`` — the thing you ``tail -f`` when a solve
    has been running for half an hour and you want to know it is still moving. It was previously
    written to only on a crash, so a healthy long run produced a 0-byte log and no way to tell a
    grinding solve from a wedged one."""
    try:
        with (job_dir / "worker.log").open("a") as fh:
            fh.write(f"[{time.strftime('%H:%M:%S')}] {message}\n")
    except Exception:  # pragma: no cover — best-effort
        pass


def read_progress(job_dir: Path) -> dict | None:
    """The worker's last published progress, or None if it hasn't reported yet."""
    try:
        return json.loads((job_dir / PROGRESS_FILE).read_text())
    except Exception:
        return None


def job_progress(job: SnupiJob, workspace_dir: Path) -> dict:
    """Overall progress fraction + ETA for the panel.

    Dynamics jobs publish REAL progress (a fixed GJF step count → an exact fraction, see
    ``snupi_dynamics._report_progress``), so we use it when present and derive the ETA from the
    observed rate rather than from a wall-clock guess. Everything else — and a dynamics job that
    hasn't reported its first step yet — falls back to :func:`_estimate_seconds`.
    """
    stage = job.stages[0] if job.stages else None
    overall = 0.0
    eta_seconds: float | None = None
    phase: str | None = None
    detail: dict = {}
    if job.status == SnupiStatus.completed:
        overall = 1.0
    elif job.status in (SnupiStatus.failed, SnupiStatus.stopped):
        overall = 0.0
    elif job.status == SnupiStatus.running and stage and stage.started_at:
        elapsed = time.time() - stage.started_at
        prog = read_progress(job.job_dir(workspace_dir))
        frac = (prog or {}).get("fraction")
        if frac is not None and frac > 0.0:
            phase = prog.get("phase")
            overall = min(0.99, float(frac))
            # ETA from the MEASURED rate: elapsed/frac is the projected total.
            eta_seconds = max(0.0, elapsed / max(frac, 1e-3) - elapsed)
            detail = {
                k: prog.get(k)
                for k in (
                    "step",
                    "n_steps",
                    "steps_per_s",
                    "dt_ns",
                    "n_nodes",
                    "n_blobs",
                    "attempt",
                )
                if prog.get(k) is not None
            }
        else:
            est = _estimate_seconds(job)
            overall = min(0.97, elapsed / est)
            eta_seconds = max(0.0, est - elapsed)
    return {
        "overall": overall,
        "status": job.status.value,
        "stage_status": stage.status if stage else None,
        "eta_seconds": eta_seconds,
        "phase": phase,
        "sim_seconds": job.sim_seconds,
        # Fine detail for a long-running solve: step/n_steps, the measured step rate, the auto-sized
        # dt, the node/blob counts, and the divergence-retry attempt. Empty for jobs that don't report.
        **detail,
    }


# ── Execution ─────────────────────────────────────────────────────────────────


def _cache_fem_analysis(job: SnupiJob, jd: Path, result: dict) -> None:
    """Write a ``predict_shape`` result to the job's ``display.json`` + ``rmsf.json`` and record the
    node/RMSF summary on the job — the display cache every SNUPI display mode reads (deform / flex /
    deviation / cylinders)."""
    positions = result.get("positions", [])
    (jd / "display.json").write_text(
        json.dumps(
            {
                "solver": result.get("solver"),
                "positions": positions,
                "axis": result.get(
                    "axis", []
                ),  # per-bp helix-centre nodes (cylinder rep)
            }
        )
    )
    from backend.core.cando_runner import pack_static_fem_frame_bin

    (jd / "display.bin").write_bytes(
        pack_static_fem_frame_bin(
            {
                "solver": result.get("solver"),
                "positions": positions,
                "axis": result.get("axis", []),
            },
            solver=result.get("solver"),
        )
    )
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


def solve_and_cache(job: SnupiJob, workspace_dir: Path) -> None:
    """Run ``predict_shape`` on the job's design snapshot and cache the result.

    This is the body the detached worker process executes (see :mod:`backend.core.snupi_worker`),
    and it is directly callable in-process (tests / debugging).  It writes the job's TERMINAL
    status (``completed`` / ``failed``) itself and never raises — the worker's only job is to
    call this.  FEM output is Physical-layer only; never written back into topology.
    """
    jd = job.job_dir(workspace_dir)
    try:
        design = _load_snapshot_design(jd)
        if design is None:
            raise RuntimeError("job design snapshot (design.json) missing")

        from backend.physics.fem_solver import predict_shape

        t0 = time.monotonic()
        # REAL progress out of the detached worker: the dynamics solve is a fixed number of GJF steps,
        # so it can report an exact fraction instead of the panel guessing from wall-clock. Throttled —
        # the integrator calls this every 500 steps, and we only rewrite the file when the percentage
        # actually moves, so a 60k-step run does ~100 tiny writes, not 120.
        _last = [-1.0]
        _phase_seen = [""]

        def _progress(first, second, third=None) -> None:
            # predict_shape's structural phases report (phase, local_fraction,
            # message), while the Langevin integrator reports
            # (fraction, phase, info). Normalize both contracts here and map the
            # structural phase-local counters onto one monotonic job-wide bar.
            if isinstance(first, str):
                phase = first
                local_fraction = float(second)
                info = {"message": third} if isinstance(third, str) else (third or {})
                spans = {
                    "mesh": (0.02, 0.12),
                    "solve": (0.12, 0.72),
                    "rmsf": (0.72, 0.94),
                    "thermal": (0.94, 0.99),
                }
                lo, hi = spans.get(phase, (0.02, 0.99))
                fraction = lo + max(0.0, min(1.0, local_fraction)) * (hi - lo)
            else:
                fraction = float(first)
                phase = str(second)
                info = third or {}
            moved = fraction - _last[0] >= 0.01 or fraction >= 1.0
            new_phase = phase != _phase_seen[0]
            if not (moved or new_phase):
                return
            _last[0] = max(_last[0], fraction)
            elapsed = time.monotonic() - t0
            rate = (info.get("step") or 0) / elapsed if elapsed > 0 else 0.0
            eta = (elapsed / fraction - elapsed) if fraction > 0.01 else None
            write_progress(
                jd,
                fraction,
                phase,
                {
                    **info,
                    "elapsed_s": round(elapsed, 1),
                    "steps_per_s": round(rate, 1) if rate else None,
                    "eta_s": round(eta) if eta else None,
                },
            )
            # A tail-able heartbeat. Phase changes always log; otherwise every ~10 % so a 60k-step run
            # writes ~10 lines, not hundreds.
            if new_phase:
                _phase_seen[0] = phase
                log_worker(
                    jd,
                    f"phase: {phase}  "
                    + " ".join(f"{k}={v}" for k, v in info.items() if v is not None),
                )
            elif int(fraction * 10) != int((_last[0] - 0.011) * 10):
                step, nsteps = info.get("step"), info.get("n_steps")
                bits = [f"{fraction * 100:.0f}%"]
                if step is not None and nsteps:
                    bits.append(f"step {step}/{nsteps}")
                if rate:
                    bits.append(f"{rate:.0f} steps/s")
                if eta:
                    bits.append(f"eta {eta / 60:.1f} min")
                bits.append(f"elapsed {elapsed / 60:.1f} min")
                log_worker(jd, " · ".join(bits))

        result = predict_shape(
            design,
            # Both static FEM phases and dynamics steps report into the one job-wide
            # progress stream consumed by the unified Jobs card.
            progress_cb=_progress,
            nonlinear=job.nonlinear,
            n_steps=job.n_steps,
            with_rmsf=job.with_rmsf,
            # The SNUPI delta: anisotropic per-motif 6×6 material + twist–stretch couplings +
            # compliant crossover beams (material="snupi").  A job may instead select the
            # isotropic "cando" baseline for an in-tab A/B comparison.
            material=getattr(job, "material", "snupi"),
            # G12: MgCl₂ molarity → Debye length of the SNUPI inter-helix electrostatics
            # (snupi-only; ignored by cando). Default 0.02 = SNUPI's 20 mM buffer.
            mgcl2_M=getattr(job, "mgcl2_M", 0.02),
            # Langevin structural dynamics: run a thermal trajectory and report its time-mean shape +
            # trajectory RMSF (same display payload). hydrodynamics=True → full RPY coupled friction.
            dynamics=getattr(job, "dynamics", False),
            hydrodynamics=getattr(job, "hydrodynamics", False),
            # Coarse blob hydrodynamics (1 bead / k bp) — the only mode that fits at origami scale;
            # the exact per-bp friction is dense O(N²). None = exact (guarded by check_friction_memory).
            hydro_coarse_bp=getattr(job, "hydro_coarse_bp", None),
            # Free ssDNA tails (overhangs / toeholds / dangling ends) as explicit Langevin chains,
            # displayed at their simulated positions (SS-4). Dynamics-only; a NADOC extension.
            tails=getattr(job, "tails", False),
            tail_max_nt=getattr(job, "tail_max_nt", None),
            # Anchors (Dirichlet BC) + uniform E-field body load — job-request annotations, never a
            # topology edit (C1/C2).  A field needs ≥1 anchor to hold against (COM drift);
            # predict_shape falls back to the free centroid-pinned solve if a selection resolves
            # to nothing.
            anchors=getattr(job, "anchors", None),
            field=getattr(job, "field", None),
        )
        sim_seconds = time.monotonic() - t0

        _cache_fem_analysis(job, jd, result)
        job.sim_seconds = round(sim_seconds, 2)
        for st in job.stages:
            st.status = "done"
        job.status = SnupiStatus.completed
        job.error = None
        job.save(workspace_dir)
        logger.info(
            "snupi job %s completed in %.1fs (%s solve, material=%s, %s nodes)",
            job.job_id,
            sim_seconds,
            result.get("solver"),
            getattr(job, "material", "snupi"),
            job.n_nodes,
        )

    except Exception as exc:  # noqa: BLE001
        logger.error("snupi job %s failed: %s", job.job_id, exc, exc_info=True)
        job.status = SnupiStatus.failed
        job.error = str(exc)
        for st in job.stages:
            if st.status != "done":
                st.status = "failed"
        job.save(workspace_dir)


def start_job(job: SnupiJob, workspace_dir: Path) -> None:
    """Launch the solve in a DETACHED worker subprocess (its own session) so it survives a
    ``uvicorn --reload`` restart of the dev server.  Idempotent while a live worker exists.

    The worker (``python -m backend.core.snupi_worker <ws> <job_id>``) reads the snapshot and
    writes the result + terminal status back through the job dir; a lightweight daemon reaper
    only ``wait()``s to avoid a zombie and drops the fast-path registry entry — killing it (on
    reload) does NOT kill the detached solve.
    """
    if is_running(job.job_id, workspace_dir):
        return
    jd = job.job_dir(workspace_dir)
    jd.mkdir(parents=True, exist_ok=True)
    log_fh = open(jd / "worker.log", "w")  # noqa: SIM115 — closed by the reaper thread
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "backend.core.snupi_worker",
            str(workspace_dir),
            job.job_id,
        ],
        cwd=str(_REPO_ROOT),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # own session → outlives a uvicorn --reload of the parent
    )
    job.pid = proc.pid
    # Flip the JOB status to running (not just the stage) so the panel's progress bar + ETA —
    # both gated on status==running — light up while the detached worker solves.
    job.status = SnupiStatus.running
    if job.stages:
        job.stages[0].status = "running"
        job.stages[0].started_at = time.time()
    job.save(workspace_dir)
    _STARTED[job.job_id] = proc.pid

    def _reap() -> None:
        try:
            proc.wait()  # reap the child so a finished worker isn't left a zombie
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                log_fh.close()
            except Exception:  # noqa: BLE001
                pass
            _STARTED.pop(job.job_id, None)

    threading.Thread(target=_reap, name=f"snupi-reap-{job.job_id}", daemon=True).start()


def stop_job(job_id: str, workspace_dir: Path) -> bool:
    """Stop a running SNUPI job.  Kills the detached worker (SIGTERM→SIGKILL) if it is alive —
    unlike the old in-thread solve, the subprocess IS interruptible, so a running solve dies at
    once.  Marks a still-``running`` job ``stopped``.  Returns True if a live worker was found."""
    try:
        job = SnupiJob.load(job_id, workspace_dir)
    except Exception:  # noqa: BLE001
        return False
    live = _pid_alive(job.pid)
    if live:
        _kill_pid(job.pid)
        _STARTED.pop(job_id, None)
    # Re-load: the worker may have written a terminal status between our load and the kill.
    try:
        job = SnupiJob.load(job_id, workspace_dir)
    except Exception:  # noqa: BLE001
        return live
    if job.status == SnupiStatus.running:
        job.status = SnupiStatus.stopped
        for st in job.stages:
            if st.status != "done":
                st.status = "failed"
        job.save(workspace_dir)
    return live


def reconcile_snupi_status(job: SnupiJob, workspace_dir: Path) -> SnupiJob:
    """Recover an orphaned ``running`` job whose worker died without writing a terminal status
    (SIGKILLed, or the machine rebooted).  A live worker → unchanged.  Dead worker + cached
    ``display.json`` → ``completed``; dead worker + no cache → ``stopped``.  A worker that
    survives a ``uvicorn --reload`` stays alive (pid still valid) → left ``running`` correctly."""
    if job.status != SnupiStatus.running:
        return job
    if _pid_alive(job.pid):
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
