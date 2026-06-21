"""
NAMD Runner — async segmented execution with health gates.

Manages a single NAMD job end-to-end:
  1. Runs minimization (blocking subprocess, short)
  2. Iterates segments sequentially, running NAMD for each .conf file
  3. After each segment, calls md_health.run_health_check()
  4. Updates job.json on every state change
  5. Appends to output/health.jsonl and output/metrics.jsonl
  6. Stops on health-gate failure or explicit cancellation

The runner uses asyncio.create_subprocess_exec so it doesn't block the
FastAPI event loop.  A running job's asyncio.Task is stored in _RUNNING so the
API can cancel it.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from backend.core.md_job import MdJob, MdStatus, MdHealthSample
from backend.core.md_health import run_health_check, append_health_jsonl
from backend.core.namd_metrics import parse_namd_log
from backend.core.md_protocols import segments_from_manifest

logger = logging.getLogger(__name__)


# ── Global task registry ──────────────────────────────────────────────────────

@dataclass
class _RunningHandle:
    thread: threading.Thread
    loop: Optional[asyncio.AbstractEventLoop] = None
    task: Optional[asyncio.Task] = None


_RUNNING: dict[str, _RunningHandle] = {}
_ACTIVE_PIDS: dict[str, int] = {}


def is_running(job_id: str) -> bool:
    handle = _RUNNING.get(job_id)
    return handle is not None and handle.thread.is_alive()


def _external_pid(job: MdJob) -> Optional[int]:
    """PID of a detached/restarted NAMD process for this job's current segment, found
    by scanning /proc for the stage conf in a NAMD command line — or None.

    Matching by the stage conf name (not a stored PID) is self-verifying: it cannot
    mistake a recycled PID for ours, so it is safe to signal.  Returns the PID so the
    caller can both detect AND stop/re-adopt the orphan."""
    if not (0 <= job.current_segment_idx < len(job.segments)):
        return None
    seg = job.segments[job.current_segment_idx]
    needle = f"{seg.name}.conf".encode()
    try:
        proc_dirs = list(Path("/proc").iterdir())
    except OSError:
        return None
    for proc_dir in proc_dirs:
        if not proc_dir.name.isdigit():
            continue
        try:
            cmdline = (proc_dir / "cmdline").read_bytes()
        except OSError:
            continue
        lower = cmdline.lower()
        if needle in cmdline and (b"namd" in lower or b"srun" in lower):
            try:
                return int(proc_dir.name)
            except ValueError:
                return None
    return None


def _external_process_running(job: MdJob) -> bool:
    """Detect a detached/restarted NAMD process that the in-memory registry lost."""
    return _external_pid(job) is not None


def _log_completed(log_path: Path) -> bool:
    if not log_path.exists():
        return False
    try:
        tail = log_path.read_text(errors="replace")[-8192:]
    except OSError:
        return False
    return "End of program" in tail or "WRITING VELOCITIES TO OUTPUT FILE" in tail


def _jsonl_has_segment(path: Path, segment_name: str) -> bool:
    if not path.exists():
        return False
    try:
        for line in path.read_text(errors="replace").splitlines():
            if f'"segment": "{segment_name}"' in line or f'"segment":"{segment_name}"' in line:
                return True
    except OSError:
        return False
    return False


def _segment_outputs_complete(output_dir: Path, segment_name: str) -> bool:
    return all((output_dir / f"{segment_name}.{ext}").exists() for ext in ("coor", "vel", "xsc"))


# A preparing job whose prep_progress sidecar hasn't been touched in this many
# seconds has lost its background prep task (server restart / crash) — the 1 Hz
# heartbeat would otherwise keep it fresh.  Generous enough to survive GC pauses.
_PREP_STALE_S = 30.0


def _reconcile_preparing(job: MdJob, workspace_dir: Path) -> MdJob:
    """Fail a 'preparing' job whose background prep task is gone.

    Background preparation streams a `prep_progress.json` heartbeat every second;
    if that sidecar is missing or stale the worker died (e.g. the dev server
    reloaded mid-solvation), so the job would otherwise sit in `preparing`
    forever.  Mark it failed with an actionable message instead.
    """
    from backend.core.md_prep_progress import PREP_PROGRESS_FILENAME  # noqa: PLC0415

    sidecar = job.job_dir(workspace_dir) / PREP_PROGRESS_FILENAME
    try:
        age = time.time() - sidecar.stat().st_mtime
    except FileNotFoundError:
        age = None
    if age is None or age > _PREP_STALE_S:
        job.status = MdStatus.failed
        job.error = (
            "Preparation was interrupted — its background task is no longer "
            "running (the server likely restarted or ran out of memory during "
            "solvation). Delete this job and start it again."
        )
        job.save(workspace_dir)
    return job


def reconcile_job_status(job: MdJob, workspace_dir: Path) -> MdJob:
    """Repair stale running state after server/runner interruption.

    If a NAMD segment finished but the Python runner died before writing metrics,
    health, or status, finish that post-processing step and leave the job stopped
    so the user can explicitly resume the next pending segment.
    """
    if job.status == MdStatus.preparing:
        return _reconcile_preparing(job, workspace_dir)
    if job.status != MdStatus.running or is_running(job.job_id) or _external_process_running(job):
        return job
    if not (0 <= job.current_segment_idx < len(job.segments)):
        job.status = MdStatus.completed
        job.save(workspace_dir)
        return job

    package_dir = job.package_dir(workspace_dir)
    manifest_path = package_dir / "manifest.json"
    output_dir = package_dir / "output"
    active = job.segments[job.current_segment_idx]
    log_path = package_dir / f"{active.name}.log"

    if not _log_completed(log_path):
        active.status = "failed"
        job.status = MdStatus.failed
        job.error = (
            f"Runner is no longer active and {active.name}.log does not show "
            "normal NAMD completion."
        )
        job.save(workspace_dir)
        return job

    if not manifest_path.exists():
        job.status = MdStatus.stopped
        job.error = "Runner stopped after NAMD completion; manifest.json not found for status reconciliation."
        job.save(workspace_dir)
        return job

    _, specs = segments_from_manifest(manifest_path)
    spec_by_name = {s.name: s for s in specs}
    spec = spec_by_name.get(active.name)
    if spec is None:
        job.status = MdStatus.stopped
        job.error = f"Runner stopped after NAMD completion; {active.name} not found in manifest."
        job.save(workspace_dir)
        return job

    metrics_path = output_dir / "metrics.jsonl"
    if not _jsonl_has_segment(metrics_path, active.name):
        _append_metrics_jsonl(output_dir, active.name, active.stage, log_path)

    health_path = output_dir / "health.jsonl"
    if not _jsonl_has_segment(health_path, active.name) and _segment_outputs_complete(output_dir, active.name):
        hresult = run_health_check(
            package_dir, active.name, job.name_stem,
            min_c1_paired       = spec.min_c1_paired,
            min_wc_ref_relative = spec.min_wc_ref_relative,
        )
        append_health_jsonl(output_dir, active.name, active.stage, hresult)
        job.health_samples.append(MdHealthSample(
            wall_time                = time.time(),
            stage                   = active.stage,
            segment                 = active.name,
            c1_paired_fraction      = hresult.c1_paired_fraction,
            c1_mean_ang             = hresult.c1_mean_ang,
            c1_p90_ang              = hresult.c1_p90_ang,
            wc_ref_relative_fraction = hresult.wc_ref_relative_fraction,
            wc_mean_hbond_ang       = hresult.wc_mean_hbond_ang,
            passed                  = hresult.passed,
            reason                  = hresult.reason or (hresult.error or ""),
        ))
        if not hresult.passed:
            active.status = "failed"
            job.status = MdStatus.failed
            job.error = f"Health gate failed after {active.name}: {hresult.reason or hresult.error}"
            job.save(workspace_dir)
            return job

    active.status = "done"
    job.current_segment_idx += 1
    if job.current_segment_idx >= len(job.segments):
        job.status = MdStatus.completed
        job.error = None
    else:
        job.status = MdStatus.stopped
        job.error = (
            f"Runner stopped after {active.name} completed; resume to continue "
            f"from {job.segments[job.current_segment_idx].name}."
        )
    job.save(workspace_dir)
    return job


# ── NAMD binary discovery ─────────────────────────────────────────────────────

def _namd_install_dirs() -> list[str]:
    """Conventional NAMD install dirs (``~/Applications/NAMD_*``), any version.

    Globbed rather than version-pinned so a newer NAMD release (e.g. ``NAMD_3.0.3``)
    is found without a code change.  CUDA/GPU builds sort first so they are
    preferred over CPU-only builds; within a build type, higher version strings
    sort first.  See ``docs/namd_setup.md``.
    """
    import glob
    dirs = sorted(glob.glob(os.path.expanduser("~/Applications/NAMD_*")), reverse=True)
    dirs.sort(key=lambda d: 0 if "cuda" in os.path.basename(d).lower() else 1)  # stable: CUDA first
    return dirs


def _namd_candidates() -> list[str]:
    """NAMD3 candidate paths — globbed at CALL time so a NAMD installed *after* the
    server started (e.g. via the MD Engines install flow) is detected without a
    restart."""
    return ["namd3", *(os.path.join(d, "namd3") for d in _namd_install_dirs())]

_GMX_CANDIDATES = ["gmx", "gmx_mpi", "gmx_d"]


def _resolve_namd(candidate: str) -> Optional[str]:
    """Resolve a candidate (PATH name or explicit path) to an executable, else None."""
    return shutil.which(candidate) or (
        candidate if os.path.isfile(candidate) and os.access(candidate, os.X_OK) else None
    )


def find_namd() -> str:
    """Return the first usable NAMD3 binary path.

    Resolution order:
      1. ``$NADOC_NAMD_BIN`` — explicit override (absolute path or PATH-resolvable name).
      2. ``namd3`` on ``$PATH``.
      3. Conventional ``~/Applications`` installs (CUDA/GPU build preferred over CPU).

    See ``docs/namd_setup.md`` for install guidance (WSL + GPU notes included).
    """
    override = os.environ.get("NADOC_NAMD_BIN", "").strip()
    candidates = ([override] if override else []) + _namd_candidates()
    for candidate in candidates:
        found = _resolve_namd(candidate)
        if found:
            return found
    raise RuntimeError(
        "NAMD3 not found.  Set $NADOC_NAMD_BIN to the namd3 binary, install to "
        "~/Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3, or add namd3 to "
        "PATH.  See docs/namd_setup.md."
    )


def find_gmx() -> str:
    """Return the first usable GROMACS binary path."""
    for candidate in _GMX_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
    raise RuntimeError(
        "GROMACS not found in PATH.  Install GROMACS and ensure 'gmx' is on PATH."
    )


# ── Thread defaulting ─────────────────────────────────────────────────────────

def default_threads() -> int:
    """Autodetect a sensible NAMD ``+p`` count: half the logical CPUs.

    On a 2-way-SMT machine (the common case) this equals the physical core
    count, which is the right target for NAMD's standard-CUDA offload mode —
    one PE per physical core, no hyperthread oversubscription.  Floored at 1.
    """
    return max(1, (os.cpu_count() or 2) // 2)


# ── Low-level subprocess helpers ──────────────────────────────────────────────

def _core_binding_prefix(threads: int) -> list[str]:
    """Return an optional ``taskset`` prefix for the NAMD launch.

    Applied ONLY when ``$NADOC_NAMD_CORES`` is set explicitly (e.g. ``"0-5"`` or
    ``"0,2,4,6,8,10"``) — the power-user knob for isolating NAMD on a shared box.

    Otherwise no prefix: NAMD's own ``+setcpuaffinity`` does topology-aware
    placement (one PE per physical core).  The previous auto ``0-{threads-1}``
    mask assumed one logical CPU per physical core and so collapsed onto half the
    cores on 2-way-SMT machines (adjacent siblings, e.g. cpus 0-5 == cores 0,1,2),
    re-introducing the oversubscription it was meant to prevent.
    """
    core_spec = os.environ.get("NADOC_NAMD_CORES", "").strip()
    if not core_spec:
        return []
    taskset = shutil.which("taskset")
    if not taskset:
        return []
    return [taskset, "-c", core_spec]


async def _run_namd_async(
    namd_bin: str,
    conf_name: str,
    package_dir: Path,
    log_path: Path,
    threads: int,
    devices: str,
    job_id: Optional[str] = None,
    on_spawn=None,
) -> tuple[int, Optional[int]]:
    """Run NAMD asynchronously; return (returncode, pid).

    ``on_spawn(pid)`` is invoked right after the process starts (and ``on_spawn(None)``
    when it exits) so the caller can persist the PID to job.json — that PID survives a
    server restart and lets ``stop_job`` signal an orphaned run."""
    cmd = [
        *_core_binding_prefix(threads),
        namd_bin,
        f"+p{threads}",
        "+setcpuaffinity",
        "+devices",
        devices,
        f"{conf_name}.conf",
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log_fh:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(package_dir),
            stdout=log_fh,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,   # own process group for clean kill
        )
        pid = proc.pid
        if job_id:
            _ACTIVE_PIDS[job_id] = pid
        if on_spawn:
            try: on_spawn(pid)
            except Exception: pass  # noqa: E722,S110 — persistence must never break the run
        try:
            rc = await proc.wait()
        except asyncio.CancelledError:
            _kill_process_group(pid)
            raise
        finally:
            if job_id:
                _ACTIVE_PIDS.pop(job_id, None)
            if on_spawn:
                try: on_spawn(None)
                except Exception: pass  # noqa: E722,S110
    return rc, pid


def _kill_process_group(pid: int, timeout: float = 15.0) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, OSError):
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.killpg(os.getpgid(pid), 0)   # check if still alive
        except (ProcessLookupError, OSError):
            return
        time.sleep(0.25)
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


# ── Metrics jsonl helper ──────────────────────────────────────────────────────

def _append_metrics_jsonl(output_dir: Path, segment_name: str, stage: str,
                          log_path: Path) -> None:
    if not log_path.exists():
        return
    m = parse_namd_log(log_path)
    record = {
        "wall_time":    time.time(),
        "segment":      segment_name,
        "stage":        stage,
        "ns_per_day":   m.ns_per_day,
        "temperature_k": m.temperature_k,
        "temperature_avg_k": m.temperature_avg_k,
        "pressure_bar": m.pressure_bar,
        "pressure_avg_bar": m.pressure_avg_bar,
        "gpressure_bar": m.gpressure_bar,
        "gpressure_avg_bar": m.gpressure_avg_bar,
        "volume_ang3":  m.volume_ang3,
        "n_energy_lines": m.n_energy_lines,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "metrics.jsonl").open("a") as fh:
        fh.write(json.dumps(record) + "\n")


# ── Main runner coroutine ─────────────────────────────────────────────────────

async def run_job(job: MdJob, workspace_dir: Path) -> None:
    """Async coroutine — runs until completion, failure, or cancellation."""
    package_dir = job.package_dir(workspace_dir)
    output_dir  = package_dir / "output"
    output_dir.mkdir(exist_ok=True)

    logger.info("[%s] run_job starting; package_dir=%s", job.job_id, package_dir)

    try:
        namd_bin = find_namd()
        logger.info("[%s] NAMD binary: %s", job.job_id, namd_bin)
    except RuntimeError as exc:
        logger.error("[%s] NAMD not found: %s", job.job_id, exc)
        job.status = MdStatus.failed
        job.error  = str(exc)
        job.save(workspace_dir)
        return

    # Load manifest
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.exists():
        logger.error("[%s] manifest.json not found at %s", job.job_id, manifest_path)
        job.status = MdStatus.failed
        job.error  = "manifest.json not found in package_dir"
        job.save(workspace_dir)
        return

    manifest = json.loads(manifest_path.read_text())
    min_name = manifest["minimization"]["name"]
    _, segments = segments_from_manifest(manifest_path)
    logger.info("[%s] Loaded manifest: %d segments, min=%s", job.job_id, len(segments), min_name)

    # Persist the live NAMD PID to job.json on every spawn, so a server restart can
    # still signal the orphaned process (see stop_job's restart fallback).
    def _persist_pid(p: Optional[int]) -> None:
        job.namd_pid = p
        job.save(workspace_dir)

    # ── Minimization ─────────────────────────────────────────────────────────

    min_coor = output_dir / f"{min_name}.coor"
    if not min_coor.exists():
        logger.info("[%s] Running minimization: %s", job.job_id, min_name)
        job.status = MdStatus.running
        job.save(workspace_dir)

        min_log = package_dir / f"{min_name}.log"
        rc, pid = await _run_namd_async(
            namd_bin, min_name, package_dir, min_log, job.threads, job.devices, job.job_id,
            on_spawn=_persist_pid,
        )
        if rc != 0:
            logger.error("[%s] Minimization failed rc=%d; log=%s", job.job_id, rc, min_log)
            job.status = MdStatus.failed
            job.error  = f"Minimization failed (rc={rc}). See {min_name}.log"
            job.save(workspace_dir)
            return
        logger.info("[%s] Minimization done", job.job_id)
    else:
        logger.info("[%s] Minimization already done (skipping)", job.job_id)

    # ── Segments ──────────────────────────────────────────────────────────────

    job.status = MdStatus.running
    job.save(workspace_dir)

    start_idx = job.current_segment_idx
    for idx, spec in enumerate(segments):
        if idx < start_idx:
            continue   # resume support

        # Mark segment running
        logger.info("[%s] Segment %d/%d: %s (%s)", job.job_id, idx+1, len(segments), spec.name, spec.stage)
        job.current_segment_idx = idx
        if idx < len(job.segments):
            job.segments[idx].status = "running"
        job.save(workspace_dir)

        seg_log = package_dir / f"{spec.name}.log"
        rc, pid = await _run_namd_async(
            namd_bin, spec.name, package_dir, seg_log, job.threads, job.devices, job.job_id,
            on_spawn=_persist_pid,
        )

        # Check if we were cancelled while NAMD was running
        if asyncio.current_task().cancelled():
            if pid:
                _kill_process_group(pid)
            raise asyncio.CancelledError

        if rc != 0:
            logger.error("[%s] NAMD failed rc=%d for %s; log=%s", job.job_id, rc, spec.name, seg_log)
            if idx < len(job.segments):
                job.segments[idx].status = "failed"
            job.status = MdStatus.failed
            job.error  = f"NAMD failed for {spec.name} (rc={rc}). See {spec.name}.log"
            job.save(workspace_dir)
            return

        # Append performance metrics
        _append_metrics_jsonl(output_dir, spec.name, spec.stage, seg_log)

        # Health check after every segment (10%, 50%, 100% of each stage)
        run_check = spec.percent >= 10.0
        if run_check:
            logger.info("[%s] Health check: %s", job.job_id, spec.name)
            hresult = run_health_check(
                package_dir, spec.name, job.name_stem,
                min_c1_paired       = spec.min_c1_paired,
                min_wc_ref_relative = spec.min_wc_ref_relative,
            )
            logger.info(
                "[%s] Health: c1=%.3f wc=%.3f passed=%s%s",
                job.job_id,
                hresult.c1_paired_fraction or 0.0,
                hresult.wc_ref_relative_fraction or 0.0,
                hresult.passed,
                f" FAIL: {hresult.reason or hresult.error}" if not hresult.passed else "",
            )
            append_health_jsonl(output_dir, spec.name, spec.stage, hresult)

            # Save health sample to job object
            sample = MdHealthSample(
                wall_time                = time.time(),
                stage                   = spec.stage,
                segment                 = spec.name,
                c1_paired_fraction      = hresult.c1_paired_fraction,
                c1_mean_ang             = hresult.c1_mean_ang,
                c1_p90_ang              = hresult.c1_p90_ang,
                wc_ref_relative_fraction = hresult.wc_ref_relative_fraction,
                wc_mean_hbond_ang       = hresult.wc_mean_hbond_ang,
                passed                  = hresult.passed,
                reason                  = hresult.reason or (hresult.error or ""),
            )
            job.health_samples.append(sample)

            if not hresult.passed:
                if idx < len(job.segments):
                    job.segments[idx].status = "failed"
                job.status = MdStatus.failed
                job.error  = (
                    f"Health gate failed after {spec.name}: {hresult.reason or hresult.error}"
                )
                job.save(workspace_dir)
                return

            if idx < len(job.segments):
                job.segments[idx].status = "done"
            job.current_segment_idx = idx + 1
            job.save(workspace_dir)
        else:
            if idx < len(job.segments):
                job.segments[idx].status = "done"
            job.current_segment_idx = idx + 1
            job.save(workspace_dir)

    logger.info("[%s] All segments completed", job.job_id)
    job.status = MdStatus.completed
    job.current_segment_idx = len(segments)
    job.save(workspace_dir)


# ── Public API called by routes_md ────────────────────────────────────────────

def start_job(job: MdJob, workspace_dir: Path) -> None:
    """Launch run_job in a background thread. Idempotent if already running.

    Keeping the long-running NAMD coroutine out of uvicorn's request loop lets
    the sidebar continue polling job/health/metric endpoints while simulations
    are active.
    """
    if is_running(job.job_id):
        return

    def _thread_main() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        handle = _RUNNING.get(job.job_id)
        if handle is not None:
            handle.loop = loop
        task = loop.create_task(run_job(job, workspace_dir))
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
                    j = MdJob.load(job.job_id, workspace_dir)
                    if j.status == MdStatus.running:
                        j.status = MdStatus.stopped
                        j.save(workspace_dir)
                except Exception:
                    pass
            loop.close()

    thread = threading.Thread(
        target=_thread_main,
        name=f"md-runner-{job.job_id}",
        daemon=True,
    )
    _RUNNING[job.job_id] = _RunningHandle(thread=thread)
    thread.start()


def stop_job(job_id: str, workspace_dir: Path) -> bool:
    """Cancel the running task for job_id.  Returns True if a task was found.

    Two paths: (1) the normal in-process path cancels the runner task + kills its
    process group; (2) the ORPHAN path — after a server restart the in-memory registry
    is empty but a detached NAMD may still be running — finds the orphan's PID
    (persisted ``namd_pid``, verified against /proc, falling back to a /proc scan by
    stage conf), kills it, and marks the job stopped on disk so it stays controllable."""
    handle = _RUNNING.get(job_id)
    if handle and handle.thread.is_alive():
        pid = _ACTIVE_PIDS.get(job_id)
        if pid:
            _kill_process_group(pid)
        if handle.loop is not None and handle.task is not None:
            handle.loop.call_soon_threadsafe(handle.task.cancel)
        return True

    # Orphan fallback: no live runner thread, but a detached process may persist.
    try:
        job = MdJob.load(job_id, workspace_dir)
    except Exception:  # noqa: BLE001
        return False
    if job.status != MdStatus.running:
        return False
    # Prefer the self-verifying /proc match (also confirms a persisted PID is still ours).
    pid = _external_pid(job)
    if pid is None and job.namd_pid and _pid_is_namd(job.namd_pid):
        pid = job.namd_pid
    if pid is None:
        return False
    _kill_process_group(pid)
    job.status = MdStatus.stopped
    job.namd_pid = None
    job.save(workspace_dir)
    return True


def _pid_is_namd(pid: int) -> bool:
    """True if /proc/<pid> is a live NAMD process (guards against a recycled PID)."""
    try:
        cmdline = (Path("/proc") / str(pid) / "cmdline").read_bytes().lower()
    except OSError:
        return False
    return b"namd" in cmdline or b"srun" in cmdline
