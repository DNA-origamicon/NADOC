"""
oxDNA Runner — async staged relaxation execution with health gates.

Sibling of ``namd_runner.py``.  Manages a single oxDNA relaxation job:
  1. prepare: write topology.top, conf.dat, and a self-contained design.json
     snapshot into the job dir (so health checks don't depend on live app state).
  2. iterate the 3 stages (min → relax → equil) sequentially; each stage gets its
     own subdir with a rendered input.txt and runs oxDNA via asyncio subprocess.
  3. after each stage, run an oxDNA health check (base-pair retention / clash /
     energy) and gate on it.
  4. update job.json on every state change; append health.jsonl / metrics.jsonl.
  5. stop on health-gate failure or explicit cancellation.

The long-running work runs in a background thread + asyncio loop (out of the
FastAPI request loop), exactly like the NAMD runner, so the sidebar keeps
polling job/health/progress while oxDNA runs.

oxDNA output is Physical-layer only — never written back into Design topology.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from backend.core.models import Design
from backend.core.oxdna_health import OxdnaHealthResult, run_oxdna_health_check
from backend.core.oxdna_job import OxdnaHealthSample, OxdnaJob, OxdnaStatus
from backend.core.oxdna_protocol import (
    OxdnaStageSpec,
    expected_energy_lines,
    render_stage_input,
)
from backend.physics.oxdna_interface import (
    write_configuration,
    write_mutual_traps,
    write_topology,
)

logger = logging.getLogger(__name__)


# ── Global task registry ──────────────────────────────────────────────────────

@dataclass
class _RunningHandle:
    thread: threading.Thread
    loop:   Optional[asyncio.AbstractEventLoop] = None
    task:   Optional[asyncio.Task] = None


_RUNNING: dict[str, _RunningHandle] = {}
_ACTIVE_PIDS: dict[str, int] = {}


def is_running(job_id: str) -> bool:
    handle = _RUNNING.get(job_id)
    return handle is not None and handle.thread.is_alive()


# ── oxDNA binary discovery ────────────────────────────────────────────────────

_OXDNA_CANDIDATES = [
    "oxDNA",
    os.path.expanduser("~/oxDNA/build/bin/oxDNA"),
    os.path.expanduser("~/Applications/oxDNA/build/bin/oxDNA"),
]


def find_oxdna() -> Optional[str]:
    """Return the first usable oxDNA binary path, or None if not found.

    Resolution: ``$OXDNA_BIN`` override → ``oxDNA`` on PATH → conventional
    ``~/oxDNA/build/bin/oxDNA`` (the local CUDA build location).
    """
    override = os.environ.get("OXDNA_BIN", "").strip()
    for candidate in ([override] if override else []) + _OXDNA_CANDIDATES:
        found = shutil.which(candidate) or (
            candidate if os.path.isfile(candidate) and os.access(candidate, os.X_OK) else None
        )
        if found:
            return found
    return None


def find_dnanalysis() -> Optional[str]:
    """Return the DNAnalysis binary path (built alongside oxDNA), or None.

    Used for the ground-truth H-bond count in the health check.  Resolved next to
    the oxDNA binary, or via $DNANALYSIS_BIN / PATH.
    """
    override = os.environ.get("DNANALYSIS_BIN", "").strip()
    candidates = [override] if override else []
    ox = find_oxdna()
    if ox:
        candidates.append(str(Path(ox).resolve().parent / "DNAnalysis"))
    candidates.append("DNAnalysis")
    for c in candidates:
        found = shutil.which(c) or (c if os.path.isfile(c) and os.access(c, os.X_OK) else None)
        if found:
            return found
    return None


def oxdna_available() -> dict:
    """Probe for a usable oxDNA binary (mirror md/namd-available)."""
    bin_path = find_oxdna()
    return {
        "available": bin_path is not None,
        "oxdna_bin": bin_path,
        "recommended_device": os.environ.get("OXDNA_DEVICE", "0"),
    }


# ── Prepare: write the self-contained job dir ─────────────────────────────────

def prepare_oxdna_job(
    design:        Design,
    geometry:      list[dict],
    job:           OxdnaJob,
    workspace_dir: Path,
    specs:         list[OxdnaStageSpec],
) -> None:
    """Write topology.top, conf.dat, design.json, and stages_spec.json into job dir.

    ``geometry`` is the per-nucleotide geometry list (from the geometry route /
    ``_geometry_for_design``) used to seed the initial oxDNA configuration.
    ``specs`` is persisted so the job can resume (rebuild input files) after a
    server restart without re-deriving protocol parameters.
    """
    jd = job.job_dir(workspace_dir)
    jd.mkdir(parents=True, exist_ok=True)
    write_topology(design, jd / "topology.top")
    write_configuration(design, geometry, jd / "conf.dat")
    # Mutual-trap external forces (hold designed WC pairs during the relax stages —
    # NADOC geometry starts the pairs outside oxDNA's H-bond range, so without this
    # a free MD melts the structure).
    write_mutual_traps(design, jd / "forces.txt")
    # Self-contained design snapshot for health checks (decoupled from live state).
    (jd / "design.json").write_text(design.model_dump_json())
    (jd / "stages_spec.json").write_text(
        json.dumps([asdict(s) for s in specs], indent=2)
    )


def load_stage_specs(job_dir: Path) -> list[OxdnaStageSpec]:
    """Reload the persisted OxdnaStageSpec list (for start/resume)."""
    path = job_dir / "stages_spec.json"
    if not path.exists():
        return []
    return [OxdnaStageSpec(**d) for d in json.loads(path.read_text())]


def _load_snapshot_design(job_dir: Path) -> Optional[Design]:
    snap = job_dir / "design.json"
    if not snap.exists():
        return None
    try:
        return Design.model_validate_json(snap.read_text())
    except Exception:  # noqa: BLE001
        return None


# ── Phase 2: NAMD seed handoff ──────────────────────────────────────────────────

@dataclass
class NamdSeed:
    """An oxDNA-relaxed structure ready to seed a NAMD run (Physical-layer only —
    a NAMD INPUT artifact, never written back into Design topology)."""
    design:          Design
    atomistic_model: object         # AtomisticModel (imported lazily to avoid a heavy import here)
    stage_name:      str            # oxDNA stage the coords came from (e.g. "3_equil")
    conf_path:       Path           # the last_conf.dat used
    source_job_id:   str


def _latest_relaxed_conf(job: OxdnaJob, workspace_dir: Path) -> tuple[Optional[Path], Optional[str]]:
    """Return (conf_path, stage_name) of the most-advanced stage that has a
    ``last_conf.dat`` — the relaxed (or production) coordinates."""
    for st in reversed(job.stages):
        cand = job.stage_dir(workspace_dir, st.name) / "last_conf.dat"
        if cand.exists():
            return cand, st.name
    return None, None


def build_namd_seed(job_id: str, workspace_dir: Path) -> NamdSeed:
    """Build a NAMD starting-structure seed from a completed oxDNA job.

    Reads the job's OWN ``design.json`` snapshot (never the live editor design —
    they can differ) and the latest relaxed/production ``last_conf.dat``, then
    reconstructs an atomistic model whose backbone is informed by the
    oxDNA-relaxed coordinates.  Uses the true backbone site (~1.6 nm cross-pair,
    near B-DNA) — NOT the raw oxDNA centre of mass — so the seeded duplex isn't
    too thin (which would cause the very startup clashes we're preventing).

    Raises FileNotFoundError if the snapshot or a relaxed conf is missing.
    """
    job = OxdnaJob.load(job_id, workspace_dir)
    jd  = job.job_dir(workspace_dir)
    design = _load_snapshot_design(jd)
    if design is None:
        raise FileNotFoundError(
            f"oxDNA job {job_id} has no design.json snapshot; cannot build a NAMD seed."
        )
    conf_path, stage_name = _latest_relaxed_conf(job, workspace_dir)
    if conf_path is None:
        raise FileNotFoundError(
            f"oxDNA job {job_id} has no relaxed last_conf.dat yet; run a relaxation first."
        )

    # Lazy import: cg_to_atomistic pulls scipy + atomistic; keep it off the
    # module import path (the runner is imported by lightweight route code).
    from backend.core.cg_to_atomistic import build_atomistic_model_from_cg_spline

    model = build_atomistic_model_from_cg_spline(design, conf_path)
    return NamdSeed(
        design          = design,
        atomistic_model = model,
        stage_name      = stage_name,
        conf_path       = conf_path,
        source_job_id   = job_id,
    )


# ── Progress ──────────────────────────────────────────────────────────────────

def _stage_energy_lines(stage_dir: Path) -> int:
    p = stage_dir / "energy.dat"
    if not p.exists():
        return 0
    try:
        return sum(1 for ln in p.read_text(errors="replace").splitlines() if ln.strip())
    except OSError:
        return 0


def job_progress(job: OxdnaJob, workspace_dir: Path, specs: list[OxdnaStageSpec]) -> dict:
    """Return overall + current-stage progress fractions + an ETA for the panel."""
    n = len(job.stages)
    done = sum(1 for s in job.stages if s.status == "done")
    idx = job.current_stage_idx
    stage_frac = 0.0
    eta_seconds: float | None = None
    if 0 <= idx < n and idx < len(specs):
        st = job.stages[idx]
        if st.status == "running":
            lines = _stage_energy_lines(job.stage_dir(workspace_dir, st.name))
            stage_frac = min(1.0, lines / max(1, expected_energy_lines(specs[idx])))

            # ── ETA to finish the current run (current + pending stages) ──────────
            # Rate from the live current stage; fall back to the last MD steps/s.
            steps_done = stage_frac * specs[idx].steps
            rate = None
            if st.started_at and steps_done > 0:
                rate = steps_done / max(1e-6, time.time() - st.started_at)
            if not rate or rate <= 0:
                for h in reversed(job.health_samples):
                    if h.steps_per_s:
                        rate = h.steps_per_s
                        break
            if rate and rate > 0:
                remaining = (specs[idx].steps - steps_done) + sum(
                    specs[j].steps for j in range(idx + 1, len(specs))
                )
                eta_seconds = max(0.0, remaining / rate)
    overall = (done + stage_frac) / n if n else 0.0
    return {
        "overall": overall,
        "done_stages": done,
        "total_stages": n,
        "current_stage_idx": idx,
        "stage_fraction": stage_frac,
        "eta_seconds": eta_seconds,
    }


# ── Low-level subprocess ──────────────────────────────────────────────────────

async def _run_oxdna_async(
    oxdna_bin: str,
    input_path: Path,
    stage_dir: Path,
    log_path:  Path,
    job_id:    str,
) -> tuple[int, Optional[int]]:
    """Run oxDNA on *input_path* with cwd=stage_dir; return (returncode, pid)."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log_fh:
        proc = await asyncio.create_subprocess_exec(
            oxdna_bin, str(input_path),
            cwd=str(stage_dir),
            stdout=log_fh,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        pid = proc.pid
        _ACTIVE_PIDS[job_id] = pid
        try:
            rc = await proc.wait()
        except asyncio.CancelledError:
            _kill_process_group(pid)
            raise
        finally:
            _ACTIVE_PIDS.pop(job_id, None)
    return rc, pid


def _kill_process_group(pid: int, timeout: float = 10.0) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, OSError):
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.killpg(os.getpgid(pid), 0)
        except (ProcessLookupError, OSError):
            return
        time.sleep(0.25)
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


# ── jsonl helpers ─────────────────────────────────────────────────────────────

def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(record) + "\n")


def _health_sample(stage_name: str, kind: str, res: OxdnaHealthResult,
                   steps_per_s: Optional[float]) -> OxdnaHealthSample:
    return OxdnaHealthSample(
        wall_time            = time.time(),
        stage                = stage_name,
        bp_retained_fraction = res.bp_retained_fraction,
        potential_energy     = res.potential_energy,
        max_backbone_clash   = res.max_backbone_stretch,
        steps_per_s          = steps_per_s,
        passed               = res.passed,
        reason               = res.reason or (res.error or ""),
    )


# ── Main runner coroutine ─────────────────────────────────────────────────────

async def run_job(job: OxdnaJob, workspace_dir: Path, specs: list[OxdnaStageSpec]) -> None:
    """Async coroutine — runs all stages until completion, failure, or cancel."""
    jd = job.job_dir(workspace_dir)
    logger.info("[%s] oxdna run_job starting; job_dir=%s", job.job_id, jd)

    oxdna_bin = find_oxdna()
    if oxdna_bin is None:
        job.status = OxdnaStatus.failed
        job.error = ("oxDNA binary not found. Set $OXDNA_BIN or install to "
                     "~/oxDNA/build/bin/oxDNA.")
        job.save(workspace_dir)
        return

    design = _load_snapshot_design(jd)
    if design is None:
        job.status = OxdnaStatus.failed
        job.error = "design.json snapshot missing/unreadable; cannot run health checks."
        job.save(workspace_dir)
        return

    topo = (jd / "topology.top").resolve()
    job.status = OxdnaStatus.running
    job.save(workspace_dir)

    start_idx = job.current_stage_idx
    for idx, spec in enumerate(specs):
        if idx < start_idx:
            continue

        stage_dir = job.stage_dir(workspace_dir, spec.name)
        stage_dir.mkdir(parents=True, exist_ok=True)

        # Starting configuration: design conf for stage 0, else previous last_conf.
        if idx == 0:
            conf = (jd / "conf.dat").resolve()
        else:
            conf = (job.stage_dir(workspace_dir, specs[idx - 1].name) / "last_conf.dat").resolve()

        input_path = stage_dir / "input.txt"
        forces = (jd / "forces.txt").resolve() if spec.external_forces else None
        input_path.write_text(
            render_stage_input(spec, str(topo), str(conf),
                               forces_name=str(forces) if forces else None)
        )

        logger.info("[%s] stage %d/%d: %s (%s, %d steps)",
                    job.job_id, idx + 1, len(specs), spec.name, spec.kind, spec.steps)
        job.current_stage_idx = idx
        job.stages[idx].status = "running"
        job.stages[idx].started_at = time.time()
        job.save(workspace_dir)

        t0 = time.time()
        log_path = stage_dir / "oxdna.log"
        rc, pid = await _run_oxdna_async(oxdna_bin, input_path, stage_dir, log_path, job.job_id)
        elapsed = max(1e-6, time.time() - t0)

        if asyncio.current_task().cancelled():
            if pid:
                _kill_process_group(pid)
            raise asyncio.CancelledError

        if rc != 0:
            job.stages[idx].status = "failed"
            job.status = OxdnaStatus.failed
            job.error = f"oxDNA failed for {spec.name} (rc={rc}). See {spec.name}/oxdna.log"
            job.save(workspace_dir)
            return

        # ── Health check + gate (oxDNA HBList ground truth when available) ────
        res = run_oxdna_health_check(
            design, stage_dir, kind=spec.kind, min_bp_retained=spec.min_bp_retained,
            topology_path=topo, dnanalysis_bin=find_dnanalysis(),
            salt_concentration=spec.salt_concentration,
        )
        steps_per_s = spec.steps / elapsed
        sample = _health_sample(spec.name, spec.kind, res, steps_per_s)
        job.health_samples.append(sample)
        _append_jsonl(jd / "health.jsonl", asdict(sample))
        _append_jsonl(jd / "metrics.jsonl", {
            "wall_time": time.time(), "stage": spec.name, "kind": spec.kind,
            "steps": spec.steps, "elapsed_s": elapsed, "steps_per_s": steps_per_s,
            "potential_energy": res.potential_energy,
            "energy_converged": res.energy_converged,
        })

        logger.info("[%s] %s health: bp=%s clash=%s passed=%s",
                    job.job_id, spec.name,
                    f"{res.bp_retained_fraction:.2f}" if res.bp_retained_fraction is not None else "—",
                    res.n_clashes, res.passed)

        if not res.passed:
            job.stages[idx].status = "failed"
            job.status = OxdnaStatus.failed
            job.error = f"Health gate failed after {spec.name}: {res.reason or res.error}"
            job.save(workspace_dir)
            return

        job.stages[idx].status = "done"
        job.current_stage_idx = idx + 1
        job.save(workspace_dir)

    logger.info("[%s] all stages completed", job.job_id)
    job.status = OxdnaStatus.completed
    job.current_stage_idx = len(specs)
    job.error = None
    job.save(workspace_dir)


# ── Public API ────────────────────────────────────────────────────────────────

def start_job(job: OxdnaJob, workspace_dir: Path, specs: list[OxdnaStageSpec]) -> None:
    """Launch run_job in a background thread. Idempotent if already running."""
    if is_running(job.job_id):
        return

    def _thread_main() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        handle = _RUNNING.get(job.job_id)
        if handle is not None:
            handle.loop = loop
        task = loop.create_task(run_job(job, workspace_dir, specs))
        if handle is not None:
            handle.task = task
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        finally:
            _ACTIVE_PIDS.pop(job.job_id, None)
            _RUNNING.pop(job.job_id, None)
            if task.cancelled():
                try:
                    j = OxdnaJob.load(job.job_id, workspace_dir)
                    if j.status == OxdnaStatus.running:
                        j.status = OxdnaStatus.stopped
                        j.save(workspace_dir)
                except Exception:  # noqa: BLE001
                    pass
            loop.close()

    thread = threading.Thread(target=_thread_main, name=f"oxdna-runner-{job.job_id}", daemon=True)
    _RUNNING[job.job_id] = _RunningHandle(thread=thread)
    thread.start()


def stop_job(job_id: str, workspace_dir: Path) -> bool:
    """Cancel the running task for job_id. Returns True if a task was found."""
    handle = _RUNNING.get(job_id)
    if handle and handle.thread.is_alive():
        pid = _ACTIVE_PIDS.get(job_id)
        if pid:
            _kill_process_group(pid)
        if handle.loop is not None and handle.task is not None:
            handle.loop.call_soon_threadsafe(handle.task.cancel)
        return True
    return False


def reconcile_oxdna_status(
    job: OxdnaJob,
    workspace_dir: Path,
    specs: Optional[list[OxdnaStageSpec]] = None,
) -> OxdnaJob:
    """Recover a detached job's status from disk after the runner thread died.

    A job is marked ``running`` only while an in-process runner thread owns it.
    If the backend restarts (or the thread otherwise dies) while oxDNA is mid-run,
    the persisted status stays ``running`` forever and the finished production
    run is never recognised (Show RMSD / Use-as-NAMD-seed stay disabled).

    This inspects the stage outputs on disk: a stage whose ``energy.dat`` reached
    its expected line count AND has a ``last_conf.dat`` physically finished, so we
    mark it ``done``.  If every stage finished → ``completed``; if the active
    stage was interrupted mid-run → ``stopped`` (resumable from there).  No-op for
    any job that isn't an orphaned ``running`` one.  Idempotent.
    """
    if job.status != OxdnaStatus.running:
        return job
    if is_running(job.job_id):
        return job  # a live runner owns it — leave it alone
    if specs is None:
        specs = load_stage_specs(job.job_dir(workspace_dir))
    if not specs or len(specs) < len(job.stages):
        return job  # can't size expectations; don't guess

    interrupted = False
    for idx, st in enumerate(job.stages):
        if st.status == "done":
            continue
        sdir = job.stage_dir(workspace_dir, st.name)
        expected = expected_energy_lines(specs[idx])
        complete = (
            (sdir / "last_conf.dat").exists()
            and _stage_energy_lines(sdir) >= expected
        )
        if complete and st.status != "failed":
            st.status = "done"
        else:
            interrupted = True
            break

    if all(s.status == "done" for s in job.stages):
        job.status = OxdnaStatus.completed
        job.current_stage_idx = len(job.stages)
        job.error = None
    elif interrupted:
        # The runner died partway through a stage that never finished on disk.
        job.status = OxdnaStatus.stopped
        job.current_stage_idx = next(
            (i for i, s in enumerate(job.stages) if s.status not in ("done",)),
            len(job.stages),
        )
    else:
        return job  # nothing changed (shouldn't happen — guarded above)

    job.save(workspace_dir)
    return job
