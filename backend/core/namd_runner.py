"""
NAMD Runner — async segmented execution with advisory health checks.

Manages a single NAMD job end-to-end:
  1. Runs minimization (blocking subprocess, short)
  2. Iterates segments sequentially, running NAMD for each .conf file
  3. After each segment, calls md_health.run_health_check()
  4. Updates job.json on every state change
  5. Appends to output/health.jsonl and output/metrics.jsonl
  6. Health is ADVISORY ONLY — a below-threshold checkpoint (C1' or WC) is
     recorded on the sample and surfaced as a UI warning, but never stops the
     run.  The run only stops on a NAMD subprocess failure or explicit
     cancellation.

The runner uses asyncio.create_subprocess_exec so it doesn't block the
FastAPI event loop.  A running job's asyncio.Task is stored in _RUNNING so the
API can cancel it.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from backend.core.md_job import MdJob, MdStatus, MdHealthSample
from backend.core.disk_guard import (
    ABORT_MIN_FREE_BYTES,
    DISK_ABORT_RC,
    GiB,
    free_bytes,
    wait_proc_with_disk_guard,
)
from backend.core.md_health import run_health_check, append_health_jsonl
from backend.core.namd_metrics import parse_namd_log, parse_namd_log_frames
from backend.core.md_cutoff import should_early_stop_stage
from backend.core.md_protocols import segments_from_manifest
from backend.core.md_vram import classify_failure_log_file, extract_error_line_from_file


def _classify_namd_failure(log_path: Path) -> str:
    """Classify a failed NAMD run from its log into a FAILURE_* kind.

    Drives the targeted "Fix" remedy: vram_oom → downsize, instability → gentler
    relaxation, gpu_error → retry, other → generic guidance.
    """
    return classify_failure_log_file(log_path)

logger = logging.getLogger(__name__)


# ── Global task registry ──────────────────────────────────────────────────────

@dataclass
class _RunningHandle:
    thread: threading.Thread
    loop: Optional[asyncio.AbstractEventLoop] = None
    task: Optional[asyncio.Task] = None


_RUNNING: dict[str, _RunningHandle] = {}
_ACTIVE_PIDS: dict[str, int] = {}
# Mid-run early-stop toggles: set_early_stop() stashes {job_id: bool} here while a
# job is running; the runner thread consumes it at the next chunk boundary so the
# flag flips without a relaunch AND the runner stays the sole job.json writer.
_EARLY_STOP_OVERRIDE: dict[str, bool] = {}


def active_namd_pids() -> set[int]:
    """PIDs of NAMD runs this server launched — used to exclude our own jobs from
    the external-GPU-contention check (the concurrent-job guard covers them)."""
    return set(_ACTIVE_PIDS.values())


def is_running(job_id: str) -> bool:
    handle = _RUNNING.get(job_id)
    return handle is not None and handle.thread.is_alive()


def _segment_pid(segment_name: str) -> Optional[int]:
    """PID of a running NAMD/srun process for this segment (fresh or resume conf), or None.

    Matches both ``<seg>.conf`` and any ``<seg>.resumeN.conf`` continuation conf.
    Matching by the stage conf name (not a stored PID) is self-verifying: it cannot
    mistake a recycled PID for ours, so it is safe to signal.  Including the trailing
    ``.conf`` / ``.resume`` in the needle prevents a ``..._p10`` segment from matching
    a running ``..._p100`` process.  Returns the PID so the caller can both detect AND
    stop/re-adopt the orphan.
    """
    needles = (f"{segment_name}.conf".encode(), f"{segment_name}.resume".encode())
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
        if any(n in cmdline for n in needles) and (b"namd" in lower or b"srun" in lower):
            try:
                return int(proc_dir.name)
            except ValueError:
                return None
    return None


def _external_pid(job: MdJob) -> Optional[int]:
    """PID of a detached/restarted NAMD process for this job's current segment, or None.

    Returns the PID so the caller can both detect AND stop/re-adopt the orphan."""
    if not (0 <= job.current_segment_idx < len(job.segments)):
        return None
    return _segment_pid(job.segments[job.current_segment_idx].name)


def _segment_process_running(segment_name: str) -> bool:
    """True if a NAMD/srun process is currently running this segment (fresh or resume conf)."""
    return _segment_pid(segment_name) is not None


def _external_process_running(job: MdJob) -> bool:
    """Detect a detached/restarted NAMD process that the in-memory registry lost."""
    if not (0 <= job.current_segment_idx < len(job.segments)):
        return False
    return _segment_process_running(job.segments[job.current_segment_idx].name)


async def _wait_for_segment_process(segment_name: str, poll: float = 10.0) -> None:
    """Block until an adopted (orphaned) NAMD process for this segment exits.

    Used when a NAMD run outlived its previous orchestrator (e.g. a dev-server
    reload): rather than spawn a duplicate that would corrupt the shared output
    files, the new runner waits for the survivor to finish.  Cancellable — a stop
    request interrupts the wait but leaves the orphan running (it is not ours to
    kill via the process-group registry).
    """
    while _segment_process_running(segment_name):
        await asyncio.sleep(poll)


def _read_xsc_step(xsc_path: Path) -> Optional[int]:
    """Return the NAMD step recorded in an .xsc / .restart.xsc file, or None."""
    try:
        for line in xsc_path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            return int(float(line.split()[0]))
    except (OSError, ValueError, IndexError):
        return None
    return None


def _latest_segment_log(package_dir: Path, segment_name: str) -> Path:
    """Newest of the segment's fresh log and any resume-continuation logs."""
    cands = [
        package_dir / f"{segment_name}.log",
        *sorted(package_dir.glob(f"{segment_name}.resume*.log")),
    ]
    existing = [p for p in cands if p.exists()]
    if not existing:
        return package_dir / f"{segment_name}.log"
    return max(existing, key=lambda p: p.stat().st_mtime)


def _resume_step(
    output_dir: Path, segment_name: str, total_steps: int
) -> Optional[int]:
    """Last NAMD checkpoint step for a partially-run segment, or None for a fresh run.

    Returns None when the segment already finished (final ``.coor`` present) or has
    never produced a usable ``.restart.xsc`` — both cases run NAMD from the
    previous segment's coordinates rather than from a mid-segment checkpoint.
    """
    if (output_dir / f"{segment_name}.coor").exists():
        return None
    restart_xsc = output_dir / f"{segment_name}.restart.xsc"
    if not restart_xsc.exists():
        return None
    step = _read_xsc_step(restart_xsc)
    if step is None or step <= 0:
        return None
    return min(step, int(total_steps))


# Directives the resume conf rewrites — dropped from the original conf and
# re-emitted to point at the checkpoint and run only the remaining steps.
_RESUME_DROP = {
    "binCoordinates",
    "binVelocities",
    "extendedSystem",
    "temperature",
    "reinitvels",
    "firsttimestep",
    "dcdFile",
    "xstFile",
    "run",
}


def _write_resume_conf(
    package_dir: Path,
    output_dir: Path,
    segment_name: str,
    resume_step: int,
    total_steps: int,
) -> str:
    """Write a NAMD conf that resumes a segment from its last checkpoint.

    Reads the segment's ``.restart.{coor,vel,xsc}`` (copied to a stable
    ``<seg>.resumeN.*`` input set to avoid read/write aliasing), continues the
    step counter with ``firsttimestep`` and runs only the remaining steps, and
    writes trajectory frames to a fresh ``<seg>.contN.dcd`` so the
    partial trajectory is preserved.  ``outputName`` is unchanged, so the final
    ``<seg>.{coor,vel,xsc}`` land where the next segment expects them.

    Returns the base name of the resume conf (without ``.conf``).
    """
    text = (package_dir / f"{segment_name}.conf").read_text()
    k = 1 + len(list(output_dir.glob(f"{segment_name}.cont*.dcd")))
    resume_base = f"{segment_name}.resume{k}"

    for ext in ("coor", "vel", "xsc"):
        shutil.copy2(
            output_dir / f"{segment_name}.restart.{ext}",
            output_dir / f"{resume_base}.{ext}",
        )

    kept = [
        line
        for line in text.splitlines()
        if (line.split()[0] if line.split() else "") not in _RESUME_DROP
    ]
    kept += [
        f"binCoordinates     output/{resume_base}.coor",
        f"binVelocities      output/{resume_base}.vel",
        f"extendedSystem     output/{resume_base}.xsc",
        f"dcdFile            output/{segment_name}.cont{k}.dcd",
        f"xstFile            output/{segment_name}.cont{k}.xst",
        f"firsttimestep      {int(resume_step)}",
        # NAMD 3.0.2's Tcl `run` does not accept the `upto` keyword (it fatals
        # with "first arg not norepeat").  firsttimestep already advances the
        # step label, so run only the REMAINING steps. resume_step is a restart
        # checkpoint (multiple of restartfreq, itself a multiple of
        # stepspercycle), so the remainder stays cycle-aligned.
        f"run                {int(total_steps) - int(resume_step)}",
    ]
    (package_dir / f"{resume_base}.conf").write_text("\n".join(kept) + "\n")
    return resume_base


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
    """Repair stale running state after a server/runner interruption.

    Only acts on a job left in ``running`` with no live process (this server's
    registry, an adopted orphan, or an external NAMD).  Finishes any missing
    post-processing for a completed segment, then leaves the job:

    - ``completed`` when the last segment finished,
    - ``failed``    when a segment died with no usable checkpoint, or
    - ``running``   when there is still work to do — the next pending segment, or
      the current segment partway through a NAMD checkpoint.  These resumable
      states are picked up and relaunched by ``resume_interrupted_jobs`` (startup
      + periodic supervisor); ``run_job`` then resumes mid-segment if needed.
    """
    if getattr(job, "execution_target", "local") != "local":
        # Remote job — its status is driven by the SlurmExecutor's poll pass, not
        # the local /proc reconciliation.  Leave it untouched here.
        return job
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

    # Source of truth for "segment finished" is the presence of the final
    # output files (independent of which log — fresh or resume — produced them).
    if not _segment_outputs_complete(output_dir, active.name):
        step = _read_xsc_step(output_dir / f"{active.name}.restart.xsc")
        if step and step > 0:
            # Interrupted mid-segment but a NAMD checkpoint survives → resumable.
            active.status = "running"
            job.error = (
                f"Interrupted during {active.name} at step {step}/{active.steps}; "
                "resuming from the last checkpoint."
            )
            job.save(workspace_dir)
            return job
        active.status = "failed"
        job.status = MdStatus.failed
        job.error = (
            f"{active.name} stopped with no usable checkpoint "
            "(no completed output and no restart files)."
        )
        job.save(workspace_dir)
        return job

    if not manifest_path.exists():
        job.status = MdStatus.failed
        job.error = (
            "Segment completed but manifest.json is missing for status reconciliation."
        )
        job.save(workspace_dir)
        return job

    _, specs = segments_from_manifest(manifest_path)
    spec_by_name = {s.name: s for s in specs}
    spec = spec_by_name.get(active.name)
    if spec is None:
        job.status = MdStatus.failed
        job.error = (
            f"Segment completed but {active.name} is not present in manifest.json."
        )
        job.save(workspace_dir)
        return job

    log_path = _latest_segment_log(package_dir, active.name)
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
            blocking                = hresult.blocking,
            reason                  = hresult.reason or (hresult.error or ""),
        ))
        # Health is advisory only — a below-threshold checkpoint warns and is
        # flagged in the UI, but never stops the run.
        if not hresult.passed:
            logger.warning(
                "[%s] Health warning after %s (below threshold, continuing): %s",
                job.job_id, active.name, hresult.reason or hresult.error,
            )

    active.status = "done"
    job.current_segment_idx += 1
    if job.current_segment_idx >= len(job.segments):
        job.status = MdStatus.completed
        job.error = None
    else:
        # Stay running so the supervisor relaunches the next pending segment.
        job.status = MdStatus.running
        job.error = (
            f"{active.name} completed after a runner interruption; "
            f"resuming from {job.segments[job.current_segment_idx].name}."
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


@functools.lru_cache(maxsize=8)
def namd_is_cuda_build(namd_bin: str) -> bool:
    """True if ``namd_bin`` is a CUDA/GPU build (vs a CPU-only multicore build).

    Runs the binary with no config file so it prints its startup banner
    (``NAMD 3.0.2 for Linux-x86_64-multicore-CUDA`` / ``Built with CUDA version …``)
    and exits; the presence of "CUDA" in that banner marks a GPU build.  Cached per
    path.  Matters because a CUDA-only binary runs on the GPU **even when the benchmark
    omits ``+devices``** — so a "CPU-only" trial on such a build is a fiction (it still
    uses the GPU), and the config grid must not offer it.
    """
    try:
        out = subprocess.run(
            [namd_bin], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "CUDA" in (out.stdout + out.stderr)


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
    ]
    if devices:
        cmd += ["+devices", devices]
    cmd += [f"{conf_name}.conf"]
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
            rc = await wait_proc_with_disk_guard(proc, package_dir, kill=_kill_process_group)
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

def _stage_base(segment_name: str) -> str:
    """Stage identity = segment name minus the _pNN chunk suffix."""
    return re.sub(r"_p\d+$", "", segment_name)


def _is_production_segment(segment_name: str) -> bool:
    """Production / qualification stages are sampling, not relaxation — never skip."""
    return bool(re.search(r"production|qualification", segment_name, re.I))


def _stage_last_chunk_idx(segments, idx: int) -> int:
    """Index of the last chunk sharing this segment's stage (chunks are contiguous)."""
    base = _stage_base(segments[idx].name)
    last = idx
    for j in range(idx + 1, len(segments)):
        if _stage_base(segments[j].name) == base:
            last = j
        else:
            break
    return last


def _alias_skipped_stage_outputs(
    output_dir: Path, completed_name: str, skipped_names: list[str]
) -> None:
    """Bridge the restart chain across an early-stop skip.

    Early-stop marks a stage's trailing chunks ``done`` WITHOUT running NAMD, so
    their ``.{coor,vel,xsc}`` are never written.  But the next stage's first chunk
    was packaged to restart from the *last* chunk of this stage — so its conf
    reads e.g. ``output/<...p100>.xsc``, which now never exists (FATAL: "Unable to
    open extended system file").  Copy the last actually-completed chunk's final
    coordinates onto each skipped chunk's expected output names — both the plain
    ``<seg>.{ext}`` (what the next stage's conf reads, and what
    ``_segment_outputs_complete``/``_resume_step`` check) and the ``.restart.{ext}``
    variant (in case a package wired the chain through restart files).  Physically
    sound: the stage plateaued, so its last completed chunk's coordinates are the
    stage's equilibrium — exactly what the skipped chunks would have reproduced.
    """
    for ext in ("coor", "vel", "xsc"):
        src = output_dir / f"{completed_name}.{ext}"
        if not src.exists():
            src = output_dir / f"{completed_name}.restart.{ext}"
        if not src.exists():
            logger.warning(
                "early-stop alias: no %s output for completed chunk %s — "
                "next stage may fail to restart", ext, completed_name,
            )
            continue
        for skip in skipped_names:
            shutil.copy2(src, output_dir / f"{skip}.{ext}")
            shutil.copy2(src, output_dir / f"{skip}.restart.{ext}")


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

    def _disk_floor_ok(label: str) -> bool:
        """Fail the job (don't launch) if free disk is already below the abort
        floor — starting a segment we know will trip the in-run guard just wastes
        setup time and risks wedging the disk."""
        fb = free_bytes(package_dir)
        if fb >= ABORT_MIN_FREE_BYTES:
            return True
        logger.error("[%s] Refusing to start %s: only %.1f GB free (floor %.0f GB)",
                     job.job_id, label, fb / GiB, ABORT_MIN_FREE_BYTES / GiB)
        job.status = MdStatus.failed
        job.failure_kind = "disk_full"
        job.error = (
            f"Not enough free disk to start {label}: {fb / GiB:.1f} GB free, "
            f"need at least {ABORT_MIN_FREE_BYTES / GiB:.0f} GB. "
            "Free up space (delete/archive old jobs), then resume."
        )
        job.save(workspace_dir)
        return False

    # ── Minimization ─────────────────────────────────────────────────────────

    min_coor = output_dir / f"{min_name}.coor"
    if not min_coor.exists():
        if not _disk_floor_ok("minimization"):
            return
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
            job.failure_kind = _classify_namd_failure(min_log)
            _cause = extract_error_line_from_file(min_log)
            job.error  = (f"Minimization failed (rc={rc}). {_cause} (see {min_name}.log)"
                          if _cause else f"Minimization failed (rc={rc}). See {min_name}.log")
            job.save(workspace_dir)
            return
        logger.info("[%s] Minimization done", job.job_id)
    else:
        logger.info("[%s] Minimization already done (skipping)", job.job_id)

    # ── Declash reference rebuild ─────────────────────────────────────────────
    # For declash designs, re-anchor the ENM ladder, heavy-atom restraints and
    # the C1'/WC health reference to the declashed coordinates produced by the
    # ss-excluded minimisation.  Idempotent (skips if already rebuilt), so it is
    # safe across resume.
    if manifest.get("declash"):
        from backend.core.md_protocols import rebuild_declashed_references  # noqa: PLC0415

        try:
            report = rebuild_declashed_references(package_dir, job.name_stem, min_coor)
            logger.info("[%s] Declash references: %s", job.job_id, report)
        except Exception as exc:
            logger.error("[%s] Declash reference rebuild failed: %s", job.job_id, exc)
            job.status = MdStatus.failed
            job.error = f"Declash reference rebuild failed: {exc}"
            job.save(workspace_dir)
            return

    # ── Segments ──────────────────────────────────────────────────────────────

    job.status = MdStatus.running
    # A resumed job carries an informational "interrupted/resuming" message in
    # `error` from reconcile.  Clear it now that we are actively running again so
    # the UI never shows a stale "stopped — resume to continue" banner on a live job.
    job.error = None
    job.save(workspace_dir)

    start_idx = job.current_segment_idx
    skip_until = 0            # early-stop: chunks below this were skipped as redundant
    for idx, spec in enumerate(segments):
        if idx < start_idx:
            continue   # resume support
        if idx < skip_until:
            continue   # stage plateaued; this chunk was skipped (already marked done)

        # Mark segment running
        logger.info("[%s] Segment %d/%d: %s (%s)", job.job_id, idx+1, len(segments), spec.name, spec.stage)
        job.current_segment_idx = idx
        job.error = None
        if idx < len(job.segments):
            job.segments[idx].status = "running"
        job.save(workspace_dir)

        seg_log = package_dir / f"{spec.name}.log"

        if _segment_outputs_complete(output_dir, spec.name) and _log_completed(
            _latest_segment_log(package_dir, spec.name)
        ):
            # Resumed past a segment that already finished — skip NAMD, re-run the
            # health gate below from the existing output files.
            logger.info(
                "[%s] Segment %s already complete; skipping NAMD", job.job_id, spec.name
            )
            seg_log = _latest_segment_log(package_dir, spec.name)
        elif _segment_process_running(spec.name):
            # A NAMD run for this segment outlived a previous orchestrator
            # (e.g. dev-server reload).  Adopt it instead of spawning a duplicate.
            logger.info("[%s] Adopting running NAMD for %s", job.job_id, spec.name)
            await _wait_for_segment_process(spec.name)
            seg_log = _latest_segment_log(package_dir, spec.name)
            if not (
                _segment_outputs_complete(output_dir, spec.name)
                or _log_completed(seg_log)
            ):
                logger.error(
                    "[%s] Adopted NAMD for %s ended without completing",
                    job.job_id,
                    spec.name,
                )
                if idx < len(job.segments):
                    job.segments[idx].status = "failed"
                job.status = MdStatus.failed
                job.error = f"Adopted NAMD run for {spec.name} ended without completing. See {seg_log.name}"
                job.save(workspace_dir)
                return
        else:
            if not _disk_floor_ok(spec.name):
                if idx < len(job.segments):
                    job.segments[idx].status = "failed"
                    job.save(workspace_dir)
                return
            resume_step = _resume_step(output_dir, spec.name, spec.steps)
            if resume_step is not None:
                conf_name = _write_resume_conf(
                    package_dir, output_dir, spec.name, resume_step, spec.steps
                )
                seg_log = package_dir / f"{conf_name}.log"
                logger.info(
                    "[%s] Resuming %s from step %d/%d (conf=%s)",
                    job.job_id,
                    spec.name,
                    resume_step,
                    spec.steps,
                    conf_name,
                )
            else:
                conf_name = spec.name
            rc, pid = await _run_namd_async(
                namd_bin,
                conf_name,
                package_dir,
                seg_log,
                job.threads,
                job.devices,
                job.job_id,
                on_spawn=_persist_pid,
            )

            # Check if we were cancelled while NAMD was running
            if asyncio.current_task().cancelled():
                if pid:
                    _kill_process_group(pid)
                raise asyncio.CancelledError

            if rc == DISK_ABORT_RC:
                fb = free_bytes(package_dir)
                logger.error("[%s] Disk guard aborted %s: %.1f GB free",
                             job.job_id, spec.name, fb / GiB)
                if idx < len(job.segments):
                    job.segments[idx].status = "failed"
                job.status = MdStatus.failed
                job.failure_kind = "disk_full"
                job.error = (
                    f"Stopped: free disk fell below {ABORT_MIN_FREE_BYTES / GiB:.0f} GB "
                    f"while running {spec.name} ({fb / GiB:.1f} GB free). "
                    "Free up space (delete/archive old jobs), then resume."
                )
                job.save(workspace_dir)
                return

            if rc != 0:
                logger.error(
                    "[%s] NAMD failed rc=%d for %s; log=%s",
                    job.job_id,
                    rc,
                    spec.name,
                    seg_log,
                )
                if idx < len(job.segments):
                    job.segments[idx].status = "failed"
                job.status = MdStatus.failed
                job.failure_kind = _classify_namd_failure(seg_log)
                _cause = extract_error_line_from_file(seg_log)
                job.error = (f"NAMD failed for {spec.name} (rc={rc}). {_cause} (see {seg_log.name})"
                             if _cause else f"NAMD failed for {spec.name} (rc={rc}). See {seg_log.name}")
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
                ("" if hresult.passed
                 else f" WARN: {hresult.reason or hresult.error}"),
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
                blocking                = hresult.blocking,
                reason                  = hresult.reason or (hresult.error or ""),
            )
            job.health_samples.append(sample)

            # Health is advisory only — a below-threshold checkpoint (C1' or WC,
            # or a diagnostic compute error) is recorded on the sample and flagged
            # in the UI as a warning, but it never stops the run.
            if not hresult.passed:
                logger.warning(
                    "[%s] Health warning after %s (below threshold, continuing): %s",
                    job.job_id, spec.name, hresult.reason or hresult.error,
                )

            if idx < len(job.segments):
                job.segments[idx].status = "done"
            job.current_segment_idx = idx + 1
            job.save(workspace_dir)
        else:
            if idx < len(job.segments):
                job.segments[idx].status = "done"
            job.current_segment_idx = idx + 1
            job.save(workspace_dir)

        # Mid-run toggle: a POST /md/jobs/{id}/early-stop stashes an override the
        # running thread consumes here, so the flag flips without a relaunch (and
        # the runner stays the single job.json writer).
        _ov = _EARLY_STOP_OVERRIDE.pop(job.job_id, None)
        if _ov is not None and _ov != job.early_stop_relax:
            job.early_stop_relax = _ov
            job.save(workspace_dir)
            logger.info("[%s] early_stop_relax toggled mid-run -> %s", job.job_id, _ov)

        # ── Early-stop accelerator (opt-in, default OFF) ──────────────────────
        # If this stage's first chunk already shows an energy+WC plateau, its
        # remaining p50/p100 chunks are redundant — mark them done and jump to the
        # next stage.  Only fires when run_check ran (percent>=10, so wc_per_frame
        # exists), never on production/qualification stages, never on a stage's
        # last chunk.  Multi-criteria on purpose (see md_cutoff).
        if job.early_stop_relax and run_check and not _is_production_segment(spec.name):
            last_idx = _stage_last_chunk_idx(segments, idx)
            if last_idx > idx:
                frames = parse_namd_log_frames(seg_log)
                decision, diag = should_early_stop_stage(frames, hresult.wc_per_frame)
                if decision:
                    skipped_names = []
                    for j in range(idx + 1, last_idx + 1):
                        if j < len(job.segments):
                            job.segments[j].status = "done"
                        skipped_names.append(segments[j].name)
                    # Skipped chunks never ran, so their restart files are absent —
                    # bridge the chain so the next stage restarts from this chunk.
                    _alias_skipped_stage_outputs(output_dir, spec.name, skipped_names)
                    skip_until = last_idx + 1
                    job.current_segment_idx = skip_until
                    job.save(workspace_dir)
                    logger.info(
                        "[%s] early-stop: stage '%s' plateaued at %s (%s) — skipped %d chunk(s)",
                        job.job_id, spec.stage, spec.name, diag, last_idx - idx,
                    )

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
    if getattr(job, "execution_target", "local") != "local":
        # Remote (Alpine/SLURM) jobs are staged + submitted by the async
        # SlurmExecutor from the cluster endpoints/supervisor — never a local NAMD
        # thread.  The sync path is a no-op so nothing local touches a remote job.
        return
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
        run_error: Optional[BaseException] = None
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        except BaseException as exc:  # noqa: BLE001 — must not leave job stuck "running"
            run_error = exc
            logger.exception("[%s] run_job crashed", job.job_id)
        finally:
            _ACTIVE_PIDS.pop(job.job_id, None)
            _RUNNING.pop(job.job_id, None)
            try:
                j = MdJob.load(job.job_id, workspace_dir)
                if task.cancelled() and j.status == MdStatus.running:
                    # User stop — keep it from being auto-resumed, and clear the
                    # transient in-flight state so the UI shows a clean stop.
                    apply_user_stop(j)
                    j.save(workspace_dir)
                elif run_error is not None and j.status == MdStatus.running:
                    # Unexpected crash — fail rather than relaunch in a loop.
                    j.status = MdStatus.failed
                    j.error = f"Runner crashed: {run_error}"
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


def apply_user_stop(job: MdJob) -> None:
    """Mutate ``job`` into a clean user-stopped state (caller saves).

    A stop is a deliberate user action, not a failure, so it must leave NO error
    behind: (1) ``error`` is cleared — otherwise the sidebar shows an error box
    (and "Unknown error" when the field was already empty); (2) the in-flight
    segment, still marked ``running`` mid-cancel, is reverted to ``pending`` so
    the stage timeline stops spinning (it re-runs from its checkpoint on resume).
    """
    job.status = MdStatus.stopped
    job.user_stopped = True
    job.error = None
    for seg in job.segments:
        if seg.status == "running":
            seg.status = "pending"


def set_early_stop(job_id: str, enabled: bool, workspace_dir: Path) -> bool:
    """Flip a job's relaxation early-stop accelerator without relaunching it.

    Idle job → write ``early_stop_relax`` straight to ``job.json`` (safe: no runner
    thread owns the file).  Running job → stash the value in ``_EARLY_STOP_OVERRIDE``
    for the runner to consume at its next chunk boundary, leaving the runner the
    sole writer of ``job.json`` (never touch disk here).  Returns the value applied.
    """
    if is_running(job_id):
        _EARLY_STOP_OVERRIDE[job_id] = enabled
        return enabled
    job = MdJob.load(job_id, workspace_dir)
    job.early_stop_relax = enabled
    job.save(workspace_dir)
    return enabled


def pending_early_stop(job_id: str) -> Optional[bool]:
    """The mid-run early-stop value a POST stashed but the runner has not yet
    consumed at a chunk boundary, or None when nothing is queued.  The UI shows a
    "pending" state (and blocks re-toggling) while this differs from the persisted
    ``early_stop_relax`` so a slow chunk can't make the live toggle look reverted."""
    return _EARLY_STOP_OVERRIDE.get(job_id)


def stop_job(job_id: str, workspace_dir: Path) -> bool:
    """Kill the NAMD process for job_id and cancel its runner task.  Returns True
    if anything (a live task or a running process) was found and acted on.

    The kill target is resolved from three sources, most-trusted first:
      1. ``_ACTIVE_PIDS`` — a process THIS worker spawned via ``_run_namd_async``.
      2. ``_external_pid`` — a self-verifying /proc scan by the current segment's
         conf name.  This is what catches an ADOPTED orphan: after a dev-server
         reload the new worker only *waits on* the surviving NAMD
         (``_wait_for_segment_process``) and never records its PID, so ``_ACTIVE_PIDS``
         is empty even though ``_RUNNING`` has a live (waiting) handle.  Without this
         fallback a stop would cancel the wait but leave NAMD burning the GPU.
      3. persisted ``namd_pid`` — last resort, guarded by ``_pid_is_namd`` against a
         recycled PID.

    We always kill the process (when found) AND cancel the runner task (when a live
    handle exists), regardless of the on-disk status — a live NAMD for a job the user
    is stopping must die even if a prior half-stop already flipped the status."""
    try:
        job = MdJob.load(job_id, workspace_dir)
    except Exception:  # noqa: BLE001
        job = None

    pid = _ACTIVE_PIDS.get(job_id)
    if pid is None and job is not None:
        pid = _external_pid(job)
    if pid is None and job is not None and job.namd_pid and _pid_is_namd(job.namd_pid):
        pid = job.namd_pid

    handle = _RUNNING.get(job_id)
    live_handle = bool(handle and handle.thread.is_alive())

    if pid is None and not live_handle:
        return False

    # Cancel the runner task first so the CancelledError propagates out of any
    # `_wait_for_segment_process` sleep BEFORE the wait loop can re-observe the
    # now-dead process and mis-mark the segment "ended without completing".
    if live_handle and handle.loop is not None and handle.task is not None:
        handle.loop.call_soon_threadsafe(handle.task.cancel)

    if pid is not None:
        _kill_process_group(pid)

    # When a live runner thread exists it persists the stopped state itself on
    # task-cancel (see run_job's thread finally).  Only the orphan/no-handle path
    # needs to write it here.
    if job is not None and not live_handle:
        apply_user_stop(job)
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


def resume_interrupted_jobs(workspace_dir: Path) -> list[str]:
    """Relaunch any job interrupted by a server/runner death (supervisor pass).

    A job is auto-resumable when it is persisted as ``running`` but no live
    process is tracked for it, and the user did not explicitly stop it.  This
    covers every interruption shape:

    - server restarted while NAMD was active (status still ``running`` on disk);
    - the orchestrator died but NAMD survived (adopted by ``run_job``);
    - a segment was killed partway through (resumed from its NAMD checkpoint);
    - a segment finished but the next one was never launched.

    ``reconcile_job_status`` first repairs the persisted state (advancing past a
    completed segment, marking genuine failures); only jobs left ``running`` with
    pending work are relaunched.  ``run_job`` is idempotent, so calling this
    repeatedly is safe.  Returns the ids of the jobs (re)launched.

    A job the user stopped (``user_stopped``) or one already terminal
    (``completed`` / ``failed``) — including the currently-parked ones — is left
    untouched.
    """
    resumed: list[str] = []
    for job in MdJob.list_jobs(workspace_dir):
        if getattr(job, "execution_target", "local") != "local":
            continue  # remote jobs are polled by the SlurmExecutor, not resumed here
        if job.user_stopped or job.status != MdStatus.running or is_running(job.job_id):
            continue
        job = reconcile_job_status(job, workspace_dir)
        if job.status != MdStatus.running:
            continue
        if not (0 <= job.current_segment_idx < len(job.segments)):
            continue
        logger.info(
            "[%s] Auto-resuming interrupted job (segment %d/%d)",
            job.job_id,
            job.current_segment_idx + 1,
            len(job.segments),
        )
        start_job(job, workspace_dir)
        resumed.append(job.job_id)
    return resumed
