"""
CanDo FEM Runner — background execution of a single CanDo-replica shape prediction.

Sibling of ``mrdna_runner.py``, radically simplified: a CanDo job is a PURE
in-process Python solve (``backend.physics.fem_solver.predict_shape``), not an
external simulator.  There is no subprocess, no GPU, and no availability probe —
only the two solver modes (linear "Coarse" preview vs nonlinear "Fine" solve).

The runner:

  1. prepare: write a self-contained ``design.json`` snapshot into the job dir, so
     the solve (and every display read) is decoupled from live editor state.
  2. run ``predict_shape`` on the snapshot in a background daemon thread (the fine
     solve is ~1 min; the thread keeps the sidebar polling job/progress).
  3. cache the deformed positions as ``display.json`` and the per-bp RMSF as
     ``rmsf.json``.
  4. mark the job completed.

Stopping is best-effort: ``predict_shape`` is a monolithic scipy solve that can't
be interrupted mid-way, so stop sets a cancel flag; a running solve finishes, then
the thread discards the result and marks the job stopped instead of caching.

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

from backend.core.cando_job import CandoJob, CandoStatus
from backend.core.models import Design

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

def prepare_cando_job(design: Design, job: CandoJob, workspace_dir: Path) -> None:
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


# ── Progress (time-based estimate; the true completion signal is the thread) ──

def _estimate_seconds(job: CandoJob) -> float:
    """Rough wall-clock estimate for the solve, scaled by system size + mode.

    Only drives the progress bar (capped < 1.0 until the thread ends); the true
    completion signal is the runner thread finishing.  Reference: a 6HB/210
    (~1260 duplex nodes) nonlinear solve ≈ 60 s; the linear preview ≈ a few s.
    """
    nodes = max(1.0, job.n_nucleotides / 2.0)          # ≈ base pairs ≈ FEM nodes
    if job.nonlinear:
        # Corotational solve: one sparse factorisation + eigensolve per load step.
        est = 3.0 + (nodes / 1260.0) * (job.n_steps / 20.0) * 55.0
    else:
        est = 1.0 + (nodes / 1260.0) * 4.0
    if job.with_rmsf:
        est += (nodes / 1260.0) * 8.0                  # the 200-mode NMA eigensolve
    return max(2.0, est)


def job_progress(job: CandoJob, workspace_dir: Path) -> dict:
    """Overall progress fraction + ETA for the panel."""
    stage = job.stages[0] if job.stages else None
    overall = 0.0
    eta_seconds: float | None = None
    if job.status == CandoStatus.completed:
        overall = 1.0
    elif job.status in (CandoStatus.failed, CandoStatus.stopped):
        overall = 0.0
    elif job.status == CandoStatus.running and stage and stage.started_at:
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


def _cache_fem_analysis(job: CandoJob, jd: Path, result: dict) -> None:
    """Write a ``predict_shape`` result to the job's ``display.json`` + ``rmsf.json`` and record the
    node/RMSF summary on the job — the display cache every CanDo display mode reads.  Shared by the
    plain predict job and the autorefine job (which caches the analysis of its REFINED design), so
    both end as a first-class completed job whose deform/flex/deviation/cylinder toggles all work."""
    positions = result.get("positions", [])
    (jd / "display.json").write_text(json.dumps({
        "solver":    result.get("solver"),
        "positions": positions,
        "axis":      result.get("axis", []),   # per-bp helix-centre nodes (cylinder rep)
    }))
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


def _run_job(job: CandoJob, workspace_dir: Path) -> None:
    """Thread body: load the snapshot, run predict_shape, extract + cache."""
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

        # Flip the JOB status to running (not just the stage) so the panel's
        # progress bar + ETA — both gated on status==running — light up during the
        # solve.  The create route left it queued after autostart.
        job.status = CandoStatus.running
        job.stages[0].status = "running"
        job.stages[0].started_at = time.time()
        job.save(workspace_dir)

        t0 = time.monotonic()
        result = predict_shape(
            design,
            nonlinear = job.nonlinear,
            n_steps   = job.n_steps,
            with_rmsf = job.with_rmsf,
        )
        sim_seconds = time.monotonic() - t0

        if _cancelled():
            raise _Cancelled()

        _cache_fem_analysis(job, jd, result)
        job.sim_seconds = round(sim_seconds, 2)
        for st in job.stages:
            st.status = "done"
        job.status = CandoStatus.completed
        job.error = None
        job.save(workspace_dir)
        logger.info("cando job %s completed in %.1fs (%s solve, %s nodes)",
                    job.job_id, sim_seconds, result.get("solver"), job.n_nodes)

    except _Cancelled:
        job.status = CandoStatus.stopped
        for st in job.stages:
            if st.status != "done":
                st.status = "failed"
        job.save(workspace_dir)
    except Exception as exc:  # noqa: BLE001
        logger.error("cando job %s failed: %s", job.job_id, exc, exc_info=True)
        if _cancelled():
            job.status = CandoStatus.stopped
        else:
            job.status = CandoStatus.failed
            job.error = str(exc)
        for st in job.stages:
            if st.status != "done":
                st.status = "failed"
        job.save(workspace_dir)
    finally:
        _RUNNING.pop(job.job_id, None)


# ── Autorefine job ────────────────────────────────────────────────────────────

def _fmt_deg(v) -> str:
    return f"{v:.1f}°" if isinstance(v, (int, float)) else "—"


def _fmt_nm(v) -> str:
    return f"{v:.2f} nm" if isinstance(v, (int, float)) else "—"


def _metric_tail(cur: Optional[dict], tgt: Optional[dict]) -> str:
    """`· dev X→Y · curve X°→Y° · twist X°→Y°` for an event's current/target metric dicts — the
    per-iteration readout of the autorefine objective (deviation + curvature + twist, each
    current→target).  Omits a metric neither side resolves so a twist-only design shows no bogus
    curvature row."""
    cur, tgt = cur or {}, tgt or {}
    bits = []
    if cur.get("deviation") is not None or tgt.get("deviation") is not None:
        bits.append(f"dev {_fmt_nm(cur.get('deviation'))}→{_fmt_nm(tgt.get('deviation'))}")
    if cur.get("bend_deg") is not None or tgt.get("bend_deg") is not None:
        bits.append(f"curve {_fmt_deg(cur.get('bend_deg'))}→{_fmt_deg(tgt.get('bend_deg'))}")
    if cur.get("twist_deg") is not None or tgt.get("twist_deg") is not None:
        bits.append(f"twist {_fmt_deg(cur.get('twist_deg'))}→{_fmt_deg(tgt.get('twist_deg'))}")
    return (" · " + " · ".join(bits)) if bits else ""


def _format_refine_note(ev: dict) -> Optional[str]:
    """A short live-status line for the panel from a ``fem_refine`` progress event (or None to keep
    the previous note).  Covers every phase — the square density sweep + fractional twist tuning,
    the honeycomb coupled twist+bend shape solve, and the greedy deviation pass — so each iteration
    reports its full metric set (deviation, curvature, twist, combined shape error)."""
    phase = ev.get("phase")
    if phase == "density_trial":
        p, n, r, tw = ev.get("period"), ev.get("n_skips"), ev.get("rmsd"), ev.get("twist")
        tail = []
        if isinstance(tw, (int, float)):
            tail.append(f"twist {tw:.1f}°")
        if isinstance(r, (int, float)):
            tail.append(f"dev {r:.2f} nm")
        ts = (" — " + ", ".join(tail)) if tail else ""
        return f"Sweeping skip density: period {p} ({n} skips){ts}…"
    if phase == "density_best":
        return f"Best skip density: period {ev.get('period')} (dev {ev.get('rmsd', 0):.2f} nm)"
    if phase == "shape_target":
        tw, bd = ev.get("twist"), ev.get("bend")
        tgt = f"twist {_fmt_deg(tw)}" + (f", curve {_fmt_deg(bd)}" if bd is not None else "")
        return f"Solving coupled shape → {tgt}…"
    if phase == "twist_authority":
        return (f"Probing twist authority: helix {ev.get('helix_id')} "
                f"(Δtwist {_fmt_deg(ev.get('dtwist'))}/skip)…")
    if phase == "twist_bump":
        return (f"Twist tuning: helix {ev.get('helix_id')} → "
                f"twist err {_fmt_deg(ev.get('twist_err'))}…")
    if phase == "shape_iter":
        it = ev.get("iter", ev.get("iteration", 0))
        se = ev.get("shape_err")
        es = f" · err {se:.1f}°" if isinstance(se, (int, float)) else ""
        return f"Shape iter {it}{_metric_tail(ev.get('current'), ev.get('target'))}{es}"
    if phase == "hotspots":
        return f"Refining {ev.get('n', 0)} local hotspot(s)…"
    if phase == "iteration":
        it, n = ev.get("iteration", 0), ev.get("n_hotspots")
        of = f"/{n}" if n else ""
        return f"Iteration {it}{of}{_metric_tail(ev.get('current'), ev.get('target'))}"
    return None


def _run_autorefine_job(job: CandoJob, workspace_dir: Path) -> None:
    """Thread body for an autorefine job: refine the loop/skip program, AUTO-APPLY it to the
    design (reversible feature-log entry), then cache the FEM analysis of the refined design so all
    display modes work.  Runs the apply on the job's own document (``job.doc_id``)."""
    from backend.api import doc_context

    jd = job.job_dir(workspace_dir)
    handle = _RUNNING.get(job.job_id)

    def _cancelled() -> bool:
        return handle is not None and handle.cancelled

    token = doc_context.set_current_doc(job.doc_id)   # apply lands on the right document
    try:
        snapshot = _load_snapshot_design(jd)
        if snapshot is None:
            raise RuntimeError("job design snapshot (design.json) missing")
        from backend.core import cando_autorefine as car
        from backend.physics.fem_solver import predict_shape

        if _cancelled():
            raise _Cancelled()
        job.status = CandoStatus.running
        job.stages[0].status = "running"
        job.stages[0].started_at = time.time()
        job.refine_note = "Solving baseline shape…"
        job.save(workspace_dir)

        def _on_progress(ev: dict) -> None:
            note = _format_refine_note(ev)
            if note:
                job.refine_note = note
                try:
                    job.save(workspace_dir)
                except Exception:  # noqa: BLE001 — a transient save failure must not kill the run
                    pass

        t0 = time.monotonic()
        res = car.fem_refine(snapshot, nonlinear=job.nonlinear,
                             on_progress=_on_progress, should_stop=_cancelled)
        if _cancelled():
            raise _Cancelled()

        before = res["before"]["rmsd"]
        after = res["after"]["rmsd"]
        marks = res.get("converged_marks") or {}
        objective = res.get("objective", "deviation")
        # SQUARE tunes end-to-end TWIST and HONEYCOMB the coupled (twist,bend) SHAPE — for both the
        # deviation RMSD *rises* as the shape is hit (exp37/exp38), so the old rmsd gate would wrongly
        # reject the correct program.  Gate those on the shape error; honeycomb-weak still gates on RMSD.
        tw_b, tw_a = res.get("twist_before"), res.get("twist_after")
        tw_t = res.get("twist_target") or 0.0
        bd_b, bd_a, bd_t = res.get("bend_before"), res.get("bend_after"), res.get("bend_target")
        if objective in ("twist", "shape"):
            err_b = abs((tw_b if tw_b is not None else 0.0) - tw_t)
            err_a = abs((tw_a if tw_a is not None else 0.0) - tw_t)
            if objective == "shape" and bd_t is not None:
                err_b += abs((bd_b if bd_b is not None else 0.0) - bd_t)
                err_a += abs((bd_a if bd_a is not None else 0.0) - bd_t)
            improved = bool(marks) and tw_a is not None and err_a < err_b - 1e-3
        else:
            improved = bool(marks) and after < before - 1e-4
        job.refine_before_rmsd = round(before, 4)
        job.refine_after_rmsd = round(after, 4)
        job.refine_twist_before = round(tw_b, 3) if tw_b is not None else None
        job.refine_twist_after = round(tw_a, 3) if tw_a is not None else None
        job.refine_twist_target = round(tw_t, 3)
        job.refine_bend_before = round(bd_b, 3) if bd_b is not None else None
        job.refine_bend_after = round(bd_a, 3) if bd_a is not None else None
        job.refine_bend_target = round(bd_t, 3) if bd_t is not None else None
        job.refine_period = (res.get("density") or {}).get("best_period")

        refined = snapshot
        if improved:
            from backend.api import state as ds
            from backend.core.oxdna_staleness import (
                effective_feature_log_position, oxdna_design_fingerprint,
            )
            n_skip = sum(1 for bps in marks.values() for dl in bps.values() if dl == -1)
            n_loop = sum(1 for bps in marks.values() for dl in bps.values() if dl == +1)
            # Build the applied (re-sequenced) design in an isolated scratch doc, then land it on
            # the document as ONE reversible feature-log entry (build OUTSIDE the mutate callback to
            # avoid the state-lock self-deadlock — same pattern as the REST apply route).
            refined_built = car.build_refined_design(snapshot, marks)
            label = f"CanDo autorefine ({n_skip} skips, {n_loop} loops)"
            params = {"source": "cando-autorefine-job", "job_id": job.job_id,
                      "mode": res.get("mode"), "edits_kept": len(res.get("edits_kept") or []),
                      "before_rmsd": round(before, 4), "after_rmsd": round(after, 4),
                      "resequenced": True}
            updated, _report, _entry = ds.mutate_with_feature_log(
                op_kind="cando-autorefine-marks", label=label, params=params,
                fn=lambda _d: refined_built)
            refined = updated
            job.refine_applied = True
            job.refine_n_marks = n_skip + n_loop
            try:
                job.feature_log_position = effective_feature_log_position(updated)
                job.design_fingerprint = oxdna_design_fingerprint(updated)
            except Exception:  # noqa: BLE001
                pass

        if _cancelled():
            raise _Cancelled()
        # Re-snapshot the refined (or unchanged) design and cache its FEM analysis → the job now
        # behaves like a completed predict job: every display mode reads its display/rmsf/snapshot.
        (jd / "design.json").write_text(refined.model_dump_json())
        result = predict_shape(refined, nonlinear=job.nonlinear,
                               n_steps=job.n_steps, with_rmsf=job.with_rmsf)
        _cache_fem_analysis(job, jd, result)

        job.sim_seconds = round(time.monotonic() - t0, 2)
        per = f" (period {job.refine_period})" if job.refine_period else ""
        if improved and objective == "shape":
            bstr = (f", bend {bd_b:.1f}°→{bd_a:.1f}° (target {bd_t:.1f}°)"
                    if bd_t is not None and bd_b is not None and bd_a is not None else "")
            job.refine_note = (f"Applied {job.refine_n_marks} marks · twist "
                               f"{tw_b:.1f}°→{tw_a:.1f}° (target {tw_t:.1f}°){bstr}")
        elif improved and objective == "twist":
            job.refine_note = (f"Applied {job.refine_n_marks} marks{per} · twist "
                               f"{tw_b:.1f}°→{tw_a:.1f}° (target {tw_t:.1f}°, "
                               f"dev {before:.2f}→{after:.2f} nm)")
        elif improved:
            job.refine_note = (f"Applied {job.refine_n_marks} marks{per} · "
                               f"deviation {before:.2f}→{after:.2f} nm")
        elif objective in ("twist", "shape"):
            cur = f"{tw_b:.1f}°" if tw_b is not None else "—"
            job.refine_note = (f"No shape improvement (twist {cur}, target {tw_t:.1f}°) "
                               f"— nothing applied.")
        else:
            job.refine_note = f"No improvement (deviation {before:.2f} nm) — nothing applied."
        for st in job.stages:
            st.status = "done"
        job.status = CandoStatus.completed
        job.error = None
        job.save(workspace_dir)
        logger.info("cando autorefine job %s: applied=%s marks=%s rmsd %.2f→%.2f",
                    job.job_id, job.refine_applied, job.refine_n_marks, before, after)

    except _Cancelled:
        job.status = CandoStatus.stopped
        job.refine_note = "Stopped."
        for st in job.stages:
            if st.status != "done":
                st.status = "failed"
        job.save(workspace_dir)
    except Exception as exc:  # noqa: BLE001
        logger.error("cando autorefine job %s failed: %s", job.job_id, exc, exc_info=True)
        job.status = CandoStatus.stopped if _cancelled() else CandoStatus.failed
        if job.status == CandoStatus.failed:
            job.error = str(exc)
        for st in job.stages:
            if st.status != "done":
                st.status = "failed"
        job.save(workspace_dir)
    finally:
        doc_context.reset_current_doc(token)
        _RUNNING.pop(job.job_id, None)


def start_job(job: CandoJob, workspace_dir: Path) -> None:
    """Launch the job's runner in a background daemon thread. Idempotent if running.
    Dispatches by kind: ``autorefine`` refines + auto-applies + caches; else plain predict."""
    if is_running(job.job_id):
        return
    target = _run_autorefine_job if job.kind == "autorefine" else _run_job
    handle = _RunningHandle(thread=threading.Thread(
        target=target, args=(job, workspace_dir),
        name=f"cando-runner-{job.job_id}", daemon=True))
    _RUNNING[job.job_id] = handle
    handle.thread.start()


def stop_job(job_id: str, workspace_dir: Path) -> bool:
    """Stop a running CanDo job.  Sets the cancel flag; a running scipy solve can't
    be interrupted mid-way, so the flagged thread finishes the current solve, then
    discards the result and marks the job stopped.  If no thread is alive, marks a
    stray ``running`` job stopped directly.  Returns True if a live job was found."""
    handle = _RUNNING.get(job_id)
    live = handle is not None and handle.thread.is_alive()
    if handle is not None:
        handle.cancelled = True
    if not live:
        try:
            job = CandoJob.load(job_id, workspace_dir)
        except Exception:  # noqa: BLE001
            return False
        if job.status == CandoStatus.running:
            job.status = CandoStatus.stopped
            for st in job.stages:
                if st.status != "done":
                    st.status = "failed"
            job.save(workspace_dir)
    return live


def reconcile_cando_status(job: CandoJob, workspace_dir: Path) -> CandoJob:
    """Recover a detached job's status after the runner thread died (e.g. a
    ``uvicorn --reload`` restart mid-solve).  If the cached ``display.json`` exists
    the solve finished → ``completed``; otherwise the thread died without caching →
    ``stopped``.  No-op unless the job is an orphaned ``running`` one."""
    if job.status != CandoStatus.running:
        return job
    if is_running(job.job_id):
        return job
    jd = job.job_dir(workspace_dir)
    if (jd / "display.json").exists():
        job.status = CandoStatus.completed
        for st in job.stages:
            st.status = "done"
        job.save(workspace_dir)
        return job
    job.status = CandoStatus.stopped
    for st in job.stages:
        if st.status != "done":
            st.status = "failed"
    job.save(workspace_dir)
    return job
