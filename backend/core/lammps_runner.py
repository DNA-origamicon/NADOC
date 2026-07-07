"""LAMMPS (CG-DNA) oxDNA runner — prepare a job dir + launch a parallel-oxDNA run.

Phase 2 of ``project_lammps_oxdna``.  Reuses NADOC's validated oxDNA topology/conf
writers, transcodes them to a LAMMPS data file (``lammps_interface``), writes the
``in.lammps`` script, and runs ``lmp`` to completion producing a trajectory dump.

Deliberately minimal for this phase: a single MD run, no staged health gates, no MD
job-system / sidebar integration, no force mapping or dump read-back yet (all later
phases).  The engine binary is discovered by ``oxdna_runner.find_lammps`` and must be
CG-DNA-capable (``lammps_supports_cgdna``).

Layer: Physical only.  Positions/orientations LAMMPS produces are display/analysis
state — never written back into Design topology.
"""

from __future__ import annotations

import asyncio
import os
import signal
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from backend.core.lammps_job import LammpsJob, LammpsStatus
from backend.core.oxdna_runner import find_lammps, lammps_supports_cgdna
from backend.physics import lammps_interface as L
from backend.physics.oxdna_interface import write_configuration, write_topology


class LammpsError(RuntimeError):
    """LAMMPS was not found/CG-DNA-capable, or the run exited non-zero."""


def prepare_lammps_job(
    design,
    geometry: list[dict],
    job_dir: str | Path,
    params: L.LammpsInputParams | None = None,
) -> dict:
    """Write a self-contained LAMMPS oxDNA2 job into ``job_dir``.

    Emits ``topology.top`` + ``conf.dat`` via the *existing* oxDNA writers (with the
    oxDNA-native duplex seed so designed pairs start in bonding range, not NADOC's
    wide B-DNA), transcodes them to ``data.oxdna``, and renders ``in.lammps``.
    Returns a dict of the written paths + atom/bond counts.  Raises ``ValueError``
    (from the transcoder) if the design is not fully sequenced.
    """
    job = Path(job_dir)
    job.mkdir(parents=True, exist_ok=True)
    params = params or L.LammpsInputParams()

    top_path = job / "topology.top"
    conf_path = job / "conf.dat"
    write_topology(design, top_path)
    # native seed: start designed WC pairs at oxDNA's bonding geometry (no startup melt)
    write_configuration(design, geometry, conf_path, oxdna_native_seed=True)

    data_text = L.build_data_file(top_path.read_text(), conf_path.read_text())
    data_path = job / params.data_file
    data_path.write_text(data_text)

    input_path = job / "in.lammps"
    input_path.write_text(L.build_input_file(params))

    n_atoms = int(next(ln for ln in data_text.splitlines() if ln.endswith(" atoms")).split()[0])
    n_bonds = int(next(ln for ln in data_text.splitlines() if ln.endswith(" bonds")).split()[0])
    return {
        "job_dir": str(job),
        "topology": str(top_path),
        "configuration": str(conf_path),
        "data": str(data_path),
        "input": str(input_path),
        "trajectory": str(job / params.traj_file),
        "n_atoms": n_atoms,
        "n_bonds": n_bonds,
        "params": asdict(params),
    }


def build_lammps_argv(
    lmp_path: str, input_file: str, *, ranks: int = 1, mpirun: str = "mpirun"
) -> list[str]:
    """Command to launch a LAMMPS run.  PURE.

    ``ranks == 1`` → plain ``lmp -in <input>`` (correct for a serial/STUBS build).
    ``ranks > 1`` → ``mpirun -np <ranks> lmp -in <input>`` for MPI domain
    decomposition — the caller must only pass ranks>1 when ``lmp`` is an MPI build
    (a serial binary under mpirun would spawn N independent duplicate runs).
    """
    base = [lmp_path, "-in", input_file]
    if ranks > 1:
        return [mpirun, "-np", str(ranks), *base]
    return base


def resolve_lammps() -> str:
    """Return a CG-DNA-capable LAMMPS binary path, or raise ``LammpsError``."""
    path = find_lammps()
    if not path:
        raise LammpsError(
            "No LAMMPS binary found. Build it via the MD Engines panel or "
            "scripts/lammps_doctor.py --fix (see docs/lammps_setup.md).")
    if not lammps_supports_cgdna(path):
        raise LammpsError(
            f"LAMMPS at {path} was built without the CG-DNA package, so it cannot run "
            f"the oxDNA force field. Rebuild with -D PKG_CG-DNA=on.")
    return path


async def run_lammps(
    job_dir: str | Path,
    *,
    lmp_path: str | None = None,
    ranks: int = 1,
    input_file: str = "in.lammps",
    send=None,
) -> dict:
    """Run a prepared LAMMPS job to completion, streaming output.

    ``send(dict)`` (optional async callback) receives ``{"type":"log","line"}`` per
    output line and a final ``{"type":"complete", ...}``.  Returns
    ``{"rc", "trajectory", "frames"}``.  Raises ``LammpsError`` on a non-zero exit or
    if no trajectory frames were produced.
    """
    job = Path(job_dir)
    lmp = lmp_path or resolve_lammps()
    argv = build_lammps_argv(lmp, input_file, ranks=ranks)

    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=str(job),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip()
        if line and send is not None:
            await send({"type": "log", "line": line})
    rc = await proc.wait()
    if rc != 0:
        raise LammpsError(f"LAMMPS exited with code {rc}. See the job log in {job}.")

    traj = _find_trajectory(job)
    frames = _count_frames(traj) if traj else 0
    if not frames:
        raise LammpsError(
            "LAMMPS finished but produced no trajectory frames — check the input/data.")
    result = {"rc": rc, "trajectory": str(traj), "frames": frames}
    if send is not None:
        await send({"type": "complete", **result})
    return result


def _find_trajectory(job: Path) -> Path | None:
    hits = sorted(job.glob("*.lammpstrj"))
    return hits[0] if hits else None


def _count_frames(traj: Path) -> int:
    """Number of ``ITEM: TIMESTEP`` records in a LAMMPS dump (0 if unreadable)."""
    try:
        with open(traj, encoding="utf-8", errors="ignore") as fh:
            return sum(1 for ln in fh if ln.startswith("ITEM: TIMESTEP"))
    except OSError:
        return 0


# ── managed jobs (persistent, background, stoppable) ──────────────────────────
#
# The REST layer (routes_lammps) prepares a LammpsJob's dir, then launches it here.
# A run executes in its own background thread + event loop (like the oxDNA/NAMD
# runners) so it survives the request and a browser refresh; job.json is updated
# with live progress and the terminal status.

@dataclass
class _RunHandle:
    thread: threading.Thread
    loop: Optional[asyncio.AbstractEventLoop] = None
    task: Optional[asyncio.Task] = None


_RUNNING: dict[str, _RunHandle] = {}
_ACTIVE_PIDS: dict[str, int] = {}


def is_running(job_id: str) -> bool:
    h = _RUNNING.get(job_id)
    return bool(h and h.thread.is_alive())


def parse_thermo_step(line: str) -> int | None:
    """A LAMMPS thermo data row (``<step> <temp> <epair> …``) → its step, else None.

    Header rows (``Step Temp …``) and prose lines have a non-numeric first token, so
    only genuine data rows — first token an int, ≥2 whitespace columns — report a step.
    """
    p = line.split()
    if len(p) >= 2 and p[0].lstrip("-").isdigit():
        try:
            float(p[1])
        except ValueError:
            return None
        return int(p[0])
    return None


async def run_job(job: LammpsJob, workspace_dir: Path) -> None:
    """Execute a prepared LAMMPS job, updating job.json with progress + result.

    The job dir must already contain ``in.lammps`` + the data file (from
    ``prepare_lammps_job``).  Streams stdout to ``lammps.log``, tracks ``current_step``
    from the thermo output, and on exit records the trajectory frame count and a
    terminal status.  Sets ``status=failed`` (not raise) on any error so the persisted
    job carries the reason.
    """
    jd = job.job_dir(workspace_dir)
    job.status = LammpsStatus.running
    job.error = None
    job.save(workspace_dir)

    try:
        lmp = resolve_lammps()
    except LammpsError as e:
        job.status = LammpsStatus.failed
        job.error = str(e)
        job.save(workspace_dir)
        return
    job.lammps_path = lmp
    argv = build_lammps_argv(lmp, "in.lammps", ranks=job.ranks)

    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=str(jd),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,   # own process group so stop can kill the whole run
    )
    _ACTIVE_PIDS[job.job_id] = proc.pid
    job.lammps_pid = proc.pid
    job.save(workspace_dir)

    assert proc.stdout is not None
    last_save = 0.0
    with open(jd / "lammps.log", "w", encoding="utf-8") as log:
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            if not line:
                continue
            log.write(line + "\n")
            step = parse_thermo_step(line)
            if step is not None:
                job.current_step = step
                now = time.time()
                if now - last_save > 1.0:   # throttle disk writes
                    job.save(workspace_dir)
                    last_save = now
    rc = await proc.wait()
    _ACTIVE_PIDS.pop(job.job_id, None)
    job.lammps_pid = None

    traj = _find_trajectory(jd)
    job.frames = _count_frames(traj) if traj else 0
    if rc != 0:
        job.status = LammpsStatus.failed
        job.error = f"LAMMPS exited with code {rc} (see lammps.log)."
    elif job.frames == 0:
        job.status = LammpsStatus.failed
        job.error = "LAMMPS finished but produced no trajectory frames."
    else:
        job.status = LammpsStatus.completed
        job.current_step = job.steps
    job.save(workspace_dir)


def start_job(job: LammpsJob, workspace_dir: Path) -> None:
    """Launch ``run_job`` in a background thread. Idempotent if already running."""
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
                    j = LammpsJob.load(job.job_id, workspace_dir)
                    if j.status == LammpsStatus.running:
                        j.status = LammpsStatus.stopped
                        j.lammps_pid = None
                        j.save(workspace_dir)
                except Exception:  # noqa: BLE001
                    pass
            loop.close()

    thread = threading.Thread(target=_thread_main, name=f"lammps-runner-{job.job_id}", daemon=True)
    _RUNNING[job.job_id] = _RunHandle(thread=thread)
    thread.start()


def _kill_process_group(pid: int) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        return
    for _ in range(20):                       # give it up to ~2 s to exit cleanly
        try:
            os.killpg(os.getpgid(pid), 0)
        except OSError:
            return
        time.sleep(0.1)
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except OSError:
        pass


def stop_job(job_id: str, workspace_dir: Path) -> bool:
    """Stop a running LAMMPS job. Returns True if a run was found + stopped.

    In-process path: kill the process group + cancel the runner task.  Orphan path
    (server restarted → registry empty but a detached ``lmp`` may persist): kill the
    persisted PID if it is still a live LAMMPS process, and mark the job stopped.
    """
    handle = _RUNNING.get(job_id)
    if handle and handle.thread.is_alive():
        pid = _ACTIVE_PIDS.get(job_id)
        if pid:
            _kill_process_group(pid)
        if handle.loop is not None and handle.task is not None:
            handle.loop.call_soon_threadsafe(handle.task.cancel)
        return True

    try:
        job = LammpsJob.load(job_id, workspace_dir)
    except Exception:  # noqa: BLE001
        return False
    if job.status != LammpsStatus.running:
        return False
    if job.lammps_pid and _pid_is_lammps(job.lammps_pid):
        _kill_process_group(job.lammps_pid)
    job.status = LammpsStatus.stopped
    job.lammps_pid = None
    job.save(workspace_dir)
    return True


def _pid_is_lammps(pid: int) -> bool:
    """True if /proc/<pid> is a live LAMMPS process (guards against a recycled PID)."""
    try:
        cmdline = (Path("/proc") / str(pid) / "cmdline").read_bytes().lower()
    except OSError:
        return False
    return b"lmp" in cmdline or b"lammps" in cmdline


def reconcile_lammps_status(job: LammpsJob, workspace_dir: Path) -> LammpsJob:
    """Heal a job persisted ``running`` whose process is gone (server died mid-run).

    If it isn't in the live registry and its recorded PID isn't a live LAMMPS
    process, flip it to ``stopped`` so it stays controllable (no auto-resume for
    LAMMPS yet — a stopped job is simply re-launchable)."""
    if job.status != LammpsStatus.running:
        return job
    if is_running(job.job_id):
        return job
    if job.lammps_pid and _pid_is_lammps(job.lammps_pid):
        return job
    job.status = LammpsStatus.stopped
    job.lammps_pid = None
    job.save(workspace_dir)
    return job
