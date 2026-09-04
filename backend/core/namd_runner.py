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
    wait_external_proc_with_disk_guard,
    wait_proc_with_disk_guard,
)
from backend.core.md_health import (
    HealthCheckResult,
    _latest_segment_dcd,
    run_health_check,
    append_health_jsonl,
)
from backend.core.namd_metrics import (
    last_namd_timestep_fast,
    parse_namd_log,
    parse_namd_log_frames,
)
from backend.core.md_cutoff import energy_plateaued, should_early_stop_stage
from backend.core.md_protocols import minimization_status, segments_from_manifest
from backend.core.md_vram import (
    FAILURE_CELL_SHRINK,
    FAILURE_HOST_OOM,
    FAILURE_INSTABILITY,
    classify_failure_log_file,
    describe_failure_file,
    extract_error_line_from_file,
)

# A "periodic cell too small" fatal is self-healing on a checkpoint restart (the
# grid rebuilds for the shrunken box), but bound the automatic retries per segment
# so a genuinely stuck run still fails instead of resuming forever.
#
# ⚠ Resuming is only legitimate when the cell is TRIMMING (a correctly filled box loses a
# few percent in the first ~300 ps and then holds — the Aksimentiev box-trace criterion).
# When the cell is COLLAPSING the crash is a symptom of an under-filled box, and every
# resume walks further into a cell that ends up smaller than the solute; measured on
# 2hb_1xT, four resumes carried a 37 %-vacuum cell down to 62 % of its initial volume with
# the DNA in contact with its own periodic image (experiments/exp47_protocol_delta).
# _cell_shrink_diagnosis makes that distinction, and every event is recorded on the job.
MAX_CELL_SHRINK_RESUMES = 4


def _record_settle_report(job, spec, output_dir: Path, workspace_dir: Path) -> None:
    """Append this NPT stage's box-trace verdict to the job and log it.

    Best-effort and never fatal — it is a diagnostic.  The hard stop for a genuinely
    collapsing cell lives in the failure path (``_cell_shrink_diagnosis``); this is the
    signal for the far more common case of a run that never crashes but whose cell was
    quietly wrong all along.
    """
    try:
        from backend.core import md_cell_health as _cell  # noqa: PLC0415

        # Include continuation traces, as _cell_shrink_diagnosis does: after an
        # auto-resume the segment's samples are split across .xst + .contN.xst, and
        # judging "flat after 300 ps" on the last restart window alone can call a
        # settled cell unsettled (or miss a drift that only shows across the join).
        rows = _read_segment_xst(output_dir, spec.name)
        if rows.size == 0:
            return
        # SegmentSpec.timestep_fs is now a real field.  It was not, so this getattr
        # always fell through to 2.0 — and on the 4 fs ladder that halved the time
        # axis, judging the tutorial's "flat after 300 ps" criterion at 150 ps.
        dt = float(getattr(spec, "timestep_fs", 0) or 0) or 2.0
        rep = _cell.settle_report(rows, timestep_fs=dt)
        rep["timestep_fs"] = dt
        rep["segment"] = spec.name
        job.cell_settle_reports.append(rep)
        job.save(workspace_dir)
        if rep["ok"] is False:
            logger.warning(
                "[%s] %s: box did NOT settle — %s", job.job_id, spec.name, rep["reason"]
            )
        else:
            logger.info(
                "[%s] %s: cell %.1f%% of start, %s",
                job.job_id,
                spec.name,
                (
                    rep.get("volume_end_ang3", 0)
                    / max(rep.get("volume_start_ang3", 1), 1e-9)
                )
                * 100.0,
                rep["reason"],
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("settle report unavailable for %s: %s", spec.name, exc)


def _record_design_rmsd(job, spec, output_dir: Path, workspace_dir: Path) -> None:
    """Append this segment's RMSD from the IDEALISED design to the job.

    The third of the tutorial's four §3.4 equilibration criteria (their Fig. 7 — the
    hextube plateaus after ~15 ns).  NADOC measured cross-engine shape agreement but
    never the deviation from the design itself, so there was no signal for "the
    structure has stopped moving away from what I drew".

    Deliberately NOT inside ``md_health`` — that module is staged VERBATIM to compute
    nodes and imported there as a bare sibling, so it must not grow ``backend.*``
    imports, and a ``Design`` object does not exist on an Alpine node.  Local only,
    best-effort, never fatal.
    """
    try:
        import numpy as _np  # noqa: PLC0415

        from backend.core.shape_metrics import deviation_profile  # noqa: PLC0415

        design = _job_design(job, workspace_dir)
        if design is None:
            return
        from backend.api.skip_twist_tuning import core_reference_geometry  # noqa: PLC0415

        ref = core_reference_geometry(design)
        if ref is None or not len(ref):
            return

        import MDAnalysis as mda  # noqa: PLC0415

        pkg = job.package_dir(workspace_dir)
        dcd = output_dir / f"{spec.name}.dcd"
        if not dcd.exists() or dcd.stat().st_size == 0:
            return
        u = mda.Universe(str(pkg / f"{job.name_stem}.psf"), str(dcd))
        sel = u.select_atoms("name C1'") or u.select_atoms("name P")
        if not len(sel):
            return
        u.trajectory[-1]
        cand = _np.asarray(sel.positions, dtype=float) / 10.0  # Å → nm
        ref_arr = _np.asarray(ref, dtype=float)
        if cand.shape != ref_arr.shape:
            # A seeded / extended topology can carry atoms the design reference does
            # not; compare only what lines up rather than reporting a bogus number.
            n = min(len(cand), len(ref_arr))
            if n < 3:
                return
            cand, ref_arr = cand[:n], ref_arr[:n]
        prof = deviation_profile(cand, ref_arr, align=True)
        rec = {
            "segment": spec.name,
            "stage": spec.stage,
            "rmsd_nm": round(float(prof.get("rmsd_nm", float("nan"))), 4),
            "n_atoms": int(len(cand)),
        }
        job.design_rmsd_reports.append(rec)
        job.save(workspace_dir)
        logger.info(
            "[%s] %s: RMSD from the idealised design %.2f nm",
            job.job_id,
            spec.name,
            rec["rmsd_nm"],
        )
    except Exception as exc:  # noqa: BLE001 — a diagnostic must never fail a run
        logger.debug("design RMSD unavailable for %s: %s", spec.name, exc)


def _job_design(job, workspace_dir: Path):
    """The job's OWN design snapshot, or None."""
    try:
        from backend.core.models import Design  # noqa: PLC0415

        path = job.job_dir(workspace_dir) / "design.json"
        if not path.exists():
            return None
        return Design.from_json(path.read_text())
    except Exception:  # noqa: BLE001
        return None


#: Note 4's factor for softening the barostat after an abrupt box change.
PISTON_SOFTEN_FACTOR = 10.0
#: Ceiling on repeated softening — 10x once is the tutorial's advice, 10,000x is a
#: barostat that has effectively stopped responding, which is a different failure.
_PISTON_MAX_PERIOD_FS = 100_000.0

_PISTON_RE = re.compile(
    r"^([ \t]*langevinPiston(?:Period|Decay)[ \t]+)([0-9.eE+-]+)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def soften_piston(conf_text: str, factor: float = PISTON_SOFTEN_FACTOR) -> str:
    """Multiply langevinPistonPeriod/Decay by ``factor`` in a conf (pure).

    Tutorial Note 4: a box that changes abruptly destabilises the run, and making the
    cell less responsive to instantaneous pressure is the sanctioned fix.  Idempotent
    only up to :data:`_PISTON_MAX_PERIOD_FS` — past that the value is left alone, since a
    barostat that slow is not going to settle the cell either.
    """

    def _bump(m: "re.Match[str]") -> str:
        try:
            value = float(m.group(2))
        except ValueError:
            return m.group(0)
        if value >= _PISTON_MAX_PERIOD_FS:
            return m.group(0)
        return f"{m.group(1)}{value * factor:.1f}"

    return _PISTON_RE.sub(_bump, conf_text)


def _soften_piston_in_conf(conf_path: Path, job_id: str, segment: str) -> None:
    """Apply :func:`soften_piston` to a segment conf in place.  Best-effort."""
    try:
        text = conf_path.read_text()
        softened = soften_piston(text)
        if softened != text:
            conf_path.write_text(softened)
            logger.warning(
                "[%s] %s: softened the barostat %gx before auto-resume "
                "(Aksimentiev Note 4)",
                job_id,
                segment,
                PISTON_SOFTEN_FACTOR,
            )
    except Exception as exc:  # noqa: BLE001 — never block a resume on this
        logger.debug("could not soften the piston for %s: %s", segment, exc)


def _read_segment_xst(output_dir: Path, segment_name: str):
    """A segment's WHOLE box trace: its own ``.xst`` plus any ``.contN.xst``.

    An auto-resume starts a new trace file, so anything that judges a segment's cell
    must stitch them back together or it is looking at the last restart window only.
    """
    import numpy as _np  # noqa: PLC0415

    from backend.core import md_cell_health as _cell  # noqa: PLC0415

    traces = [output_dir / f"{segment_name}.xst"]
    traces += sorted(output_dir.glob(f"{segment_name}.cont*.xst"))
    rows = _np.zeros((0, 4))
    for t in traces:
        r = _cell.read_xst(t)
        if r.size:
            rows = r if rows.size == 0 else _np.vstack([rows, r])
    return rows


def _cell_shrink_diagnosis(output_dir: Path, segment_name: str) -> dict:
    """How far has the cell moved, and is that a trim or a collapse?

    Reads the segment's own ``.xst`` (plus any ``.contN.xst`` continuations, which is
    where an earlier auto-resume wrote), so the verdict covers the whole segment rather
    than the last restart window.
    """
    from backend.core import md_cell_health as _cell  # noqa: PLC0415

    rows = _read_segment_xst(output_dir, segment_name)
    if rows.size == 0:
        return {
            "volume_fraction": float("nan"),
            "collapsing": False,
            "cell_start_ang": None,
            "cell_end_ang": None,
            "n_samples": 0,
        }
    frac = _cell.volume_fraction(rows)
    return {
        "volume_fraction": frac,
        "collapsing": _cell.is_collapsing(rows),
        "cell_start_ang": [round(float(x), 2) for x in rows[0, 1:]],
        "cell_end_ang": [round(float(x), 2) for x in rows[-1, 1:]],
        "n_samples": int(rows.shape[0]),
    }


# A host pinned-memory OOM (cudaHostAlloc in the bonded-CUDA tuple staging — see
# md_vram.FAILURE_HOST_OOM) is usually TRANSIENT: the same allocation succeeds when
# the host isn't momentarily starved (e.g. another process spiked, or NADOC's own
# live-model rebuild competed for RAM). The supervisor relaunch is on a ~30 s cadence,
# giving that pressure time to clear, so a bounded auto-resume turns the barrier into
# an invisible hiccup. A genuinely under-RAM machine exhausts the cap and then fails
# normally (with the host-OOM Fix popup), so it never loops forever.
MAX_HOST_OOM_RESUMES = 3

# A RATTLE / "atoms moving too fast" blow-up (FAILURE_INSTABILITY) is a STRAINED-SEED
# problem, not a transient — re-running the same rigidBonds-all + 4 fs conf from the same
# coordinates just re-crashes. The automatic remedy is to SOFTEN the integrator (drop
# rigidBonds + 4 fs → the proven-stable rigidBonds-none + 1 fs the ladder's gentle first
# chunk uses), so one auto-resume is enough. If the softened 1 fs run STILL blows up the
# seed is genuinely un-relaxable and the job dead-ends (instability Fix popup) rather than
# looping — belt-and-braces with the "conf already soft → not re-softened" guard below.
MAX_INSTABILITY_RESUMES = 1

# Before spawning a NAMD segment, if free host RAM is below this floor, release
# NADOC's own live-viewer atomistic model cache so the run has headroom to pin its
# GPU staging buffers. On a roomy machine free RAM stays above the floor and nothing
# is dropped (no viewer thrash); it only bites when the host is genuinely tight.
_HOST_HEADROOM_FLOOR_MB = 4096


def _free_host_ram_for_namd(job_id: str, phase: str) -> None:
    """Reclaim NADOC's discretionary host RAM before a NAMD spawn (best-effort)."""
    try:
        from backend.core.atomistic_cache import reclaim_cache_if_low  # noqa: PLC0415

        freed = reclaim_cache_if_low(_HOST_HEADROOM_FLOOR_MB)
        if freed:
            logger.info(
                "[%s] Host RAM low before %s; released %d cached atomistic model(s) "
                "to give NAMD pinning headroom.",
                job_id,
                phase,
                freed,
            )
    except Exception:  # noqa: BLE001 — reclaim must never break a run
        pass


def _classify_namd_failure(log_path: Path) -> str:
    """Classify a failed NAMD run from its log into a FAILURE_* kind.

    Drives the targeted "Fix" remedy: vram_oom → downsize, host_oom (pinned CPU
    RAM) → free-RAM-and-resume, instability → gentler relaxation, gpu_error →
    retry, other → generic guidance.
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
        if any(n in cmdline for n in needles) and (
            b"namd" in lower or b"srun" in lower
        ):
            try:
                return int(proc_dir.name)
            except ValueError:
                return None
    return None


def _external_pid(job: MdJob) -> Optional[int]:
    """PID of a detached/restarted NAMD process for this job's current segment, or None.

    Minimization is not in ``job.segments``; check its dedicated timeline row first.
    Without this, a server reload during a long seeded minimization made Stop cancel
    only the adopter task and leave NAMD alive, after which the supervisor adopted it
    again and the UI appeared to restart the job.

    Returns the PID so the caller can both detect AND stop/re-adopt the orphan."""
    minimization = getattr(job, "minimization", None)
    if minimization is not None and minimization.status == "running":
        pid = _segment_pid(minimization.name)
        if pid is not None:
            return pid
    if not (0 <= job.current_segment_idx < len(job.segments)):
        return None
    return _segment_pid(job.segments[job.current_segment_idx].name)


def _segment_process_running(segment_name: str) -> bool:
    """True if a NAMD/srun process is currently running this segment (fresh or resume conf)."""
    return _segment_pid(segment_name) is not None


def _package_process_running(package_dir: Path) -> bool:
    """True if ANY NAMD process is running out of *package_dir* (its cwd).

    Broader than :func:`_segment_process_running`, which matches one segment's conf
    name — and therefore cannot see a running **minimisation** (``*_00_min_*.conf``),
    because that is not a segment.  That blind spot silently failed jobs: an
    interruption during minimisation (a dev-server ``--reload``, or any server
    restart) left ``reconcile_job_status`` unable to see the live NAMD, so it looked
    at the not-yet-started first segment, found no checkpoint, and declared the job
    failed — while NAMD carried on minimising as an orphan.

    Matching on cwd is self-verifying like the conf-name match: a recycled PID whose
    cwd is this package is, by construction, this job's process.
    """
    try:
        target = package_dir.resolve()
    except OSError:
        return False
    try:
        proc_dirs = list(Path("/proc").iterdir())
    except OSError:
        return False
    for proc_dir in proc_dirs:
        if not proc_dir.name.isdigit():
            continue
        try:
            if b"namd" not in (proc_dir / "cmdline").read_bytes().lower():
                continue
            if (proc_dir / "cwd").resolve() == target:
                return True
        except OSError:  # process exited, or not ours to inspect
            continue
    return False


def _external_process_running(job: MdJob, workspace_dir: Optional[Path] = None) -> bool:
    """Detect a detached/restarted NAMD process that the in-memory registry lost.

    Checks the current segment AND (via cwd) any other NAMD running out of this job's
    package — notably the minimisation, which owns no segment name.
    """
    if 0 <= job.current_segment_idx < len(job.segments) and _segment_process_running(
        job.segments[job.current_segment_idx].name
    ):
        return True
    if workspace_dir is not None:
        try:
            return _package_process_running(job.package_dir(workspace_dir))
        except Exception:  # noqa: BLE001
            return False
    return False


async def _wait_for_segment_process(
    segment_name: str,
    poll: float = 10.0,
    *,
    guard_dir: Optional[Path] = None,
    on_tick=None,
) -> int:
    """Block until an adopted (orphaned) NAMD process for this segment exits.

    Used when a NAMD run outlived its previous orchestrator (e.g. a dev-server
    reload): rather than spawn a duplicate that would corrupt the shared output
    files, the new runner waits for the survivor to finish.  Cancellable — a stop
    request interrupts the wait but leaves the orphan running (it is not ours to
    kill via the process-group registry).

    An adopted segment gets the SAME orchestration services as one we spawned
    ourselves: the disk guard and the in-flight ``on_tick`` probe both run here, via
    the shared loop in ``disk_guard``.  They used to run only inside
    :func:`_run_namd_async`, which this path never calls — so an adopted run silently
    lost both its low-disk abort and its health sampling for the whole segment.

    Returns the same rc vocabulary as :func:`_run_namd_async`: ``0`` when the adopted
    process exited, :data:`DISK_ABORT_RC` when the guard stopped it.  ``guard_dir``
    is optional so callers with nothing to guard keep the plain wait.
    """
    if guard_dir is None:
        while _segment_process_running(segment_name):
            await asyncio.sleep(poll)
        return 0

    def _kill_adopted() -> None:
        pid = _segment_pid(segment_name)
        if pid is not None:
            _kill_process_group(pid)

    return await wait_external_proc_with_disk_guard(
        lambda: _segment_process_running(segment_name),
        guard_dir,
        kill=_kill_adopted,
        poll_s=poll,
        on_tick=on_tick,
    )


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


#: Keys that make a metrics/health JSONL record worth keeping.  If every one of them is
#: null the record carries no information and must not block a recompute.
_JSONL_SUBSTANTIVE_KEYS = (
    "c1_paired_fraction",
    "wc_ref_relative_fraction",  # health.jsonl
    "temperature_k",
    "pressure_bar",
    "total_energy_kcal",
    "ns_per_day",
    "volume_ang3",  # metrics.jsonl
)


def _jsonl_has_segment(path: Path, segment_name: str) -> bool:
    """Has this segment already been recorded in a metrics/health JSONL?

    Parsed rather than substring-matched, and — importantly — a record whose every
    value came back empty does NOT count as recorded.  A record written from a
    truncated or not-yet-flushed log has all-``None`` scalars, and treating that as
    "done" pinned the segment to blank metrics forever: nothing ever recomputed it even
    after the log had grown.  A record that carries a real ``error`` DOES count, so a
    legitimately-failed check is not re-run on every supervisor pass.
    """
    if not path.exists():
        return False
    try:
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn final line — treat as not-yet-written
            if rec.get("segment") != segment_name:
                continue
            if rec.get("error"):
                return True  # a real failure; do not recompute it endlessly
            if any(rec.get(k) is not None for k in _JSONL_SUBSTANTIVE_KEYS):
                return True
            # else: an all-empty record — fall through so it can be rewritten
    except OSError:
        return False
    return False


def _segment_outputs_complete(output_dir: Path, segment_name: str) -> bool:
    return all(
        (output_dir / f"{segment_name}.{ext}").exists()
        for ext in ("coor", "vel", "xsc")
    )


# A preparing job whose prep_progress sidecar hasn't been touched in this many
# seconds has lost its background prep task (server restart / crash) — the 1 Hz
# heartbeat would otherwise keep it fresh.  Generous enough to survive GC pauses.
_PREP_STALE_S = 30.0
_PREP_INTERRUPTED_PREFIX = "Preparation was interrupted"


def _reconcile_preparing(job: MdJob, workspace_dir: Path) -> MdJob:
    """Fail a 'preparing' job whose background prep task is gone.

    Background preparation streams a `prep_progress.json` heartbeat every second;
    if that sidecar is missing or stale the worker died (e.g. the dev server
    reloaded mid-solvation), so the job would otherwise sit in `preparing`
    forever.  Mark it failed with an actionable message instead.
    """
    from backend.core.md_prep_progress import (  # noqa: PLC0415
        PREP_PROGRESS_FILENAME,
        is_active_preparation,
    )

    # The task registry is authoritative inside this server process. Heartbeat age is
    # only a crash/restart heuristic and can be stale while GIL-heavy atomistic assembly
    # prevents the event loop from scheduling its one-second writer.
    if is_active_preparation(job.job_id):
        return job

    sidecar = job.job_dir(workspace_dir) / PREP_PROGRESS_FILENAME
    try:
        age = time.time() - sidecar.stat().st_mtime
    except FileNotFoundError:
        age = None
    if age is None or age > _PREP_STALE_S:
        job.status = MdStatus.failed
        job.error = (
            f"{_PREP_INTERRUPTED_PREFIX} — its background task is no longer "
            "running (the server likely restarted or ran out of memory during "
            "solvation). Delete this job and start it again."
        )
        job.save(workspace_dir)
    return job


def _reconcile_min_name(job: MdJob, manifest_path: Path) -> Optional[str]:
    """The minimisation output stem, from the job or its manifest, or None.

    The manifest is authoritative (it is what ``run_job`` itself reads), with the job's
    own timeline row as the fallback for a package whose manifest is unreadable.  None
    means "cannot tell" — callers must then leave minimisation-state judgements alone
    rather than guess.
    """
    try:
        name = json.loads(manifest_path.read_text())["minimization"]["name"]
        if isinstance(name, str) and name:
            return name
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return getattr(getattr(job, "minimization", None), "name", None) or None


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
    # A completed package is stronger evidence than a transient stale-heartbeat
    # verdict.  Older workers could stop heartbeating at 100% while still writing
    # final assets, then finish by setting QUEUED without clearing the false error.
    # Heal those already-persisted records on the next list/status reconciliation.
    if (
        job.status == MdStatus.queued
        and (job.error or "").startswith(_PREP_INTERRUPTED_PREFIX)
        and (job.package_dir(workspace_dir) / "manifest.json").exists()
    ):
        job.error = None
        job.failure_kind = None
        job.save(workspace_dir)

    # Package preparation is local for every target, including Alpine and RunPod.
    # Reconcile its heartbeat before handing launched remote jobs to their remote
    # supervisors; otherwise a server reload leaves remote drafts preparing forever.
    if job.status == MdStatus.preparing:
        return _reconcile_preparing(job, workspace_dir)
    if getattr(job, "execution_target", "local") != "local":
        # Remote job — its status is driven by the SlurmExecutor / RunPod supervisor
        # poll pass, not the local /proc reconciliation.  Leave it untouched, EXCEPT
        return job
    # workspace_dir lets the check also see a running MINIMISATION (it owns no segment
    # name).  Without it, a restart during minimisation failed the job under a live NAMD.
    if (
        job.status != MdStatus.running
        or is_running(job.job_id)
        or _external_process_running(job, workspace_dir)
    ):
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
    # This is checked FIRST: completed outputs are stronger evidence than any
    # inference below, and a finished segment must be advanced past even if the
    # minimisation coordinates it chained from have since been cleaned up.
    if not _segment_outputs_complete(output_dir, active.name):
        # ── Interrupted during MINIMISATION ───────────────────────────────────
        # Every segment chains from `output/<min>.coor` (its conf's binCoordinates),
        # so while that file is absent no segment can have run — the interruption
        # landed in the minimisation window, which is many minutes on a large system.
        # Without this the code below judged the job by a segment that had never
        # started, found neither outputs nor a restart file, and failed the whole job
        # with an error naming the wrong stage; `resume_interrupted_jobs` then skipped
        # it, so the advertised "server restarted while NAMD was active" recovery did
        # not in fact cover minimisation.  (Its sibling — a minimisation that OUTLIVES
        # the orchestrator — is handled by `_external_process_running` above; this is
        # the case where the NAMD child died too.  See tests/test_md_min_orphan.py.)
        #
        # The condition mirrors `run_job`'s own precondition for (re-)running
        # minimisation exactly, so the two can never disagree about what happens next.
        # Leaving the job `running` is safe against a relaunch loop: a minimisation that
        # truly cannot run fails inside `run_job`, with the real rc and log.
        min_name = _reconcile_min_name(job, manifest_path)
        if min_name and not (output_dir / f"{min_name}.coor").exists():
            if job.minimization is not None and job.minimization.status == "running":
                job.minimization.status = "pending"
            job.status = MdStatus.running
            job.error = (
                f"Interrupted during minimisation ({min_name}); "
                "it will re-run on resume."
            )
            job.save(workspace_dir)
            return job

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
        # No checkpoint. Distinguish "died" from "never got to start", because the
        # window between minimisation finishing and the first segment launching is
        # not instantaneous — the GPU-resident pre-flight probe and the declash
        # reference rebuild both live there, and both take real time on a large
        # system.  A restart landing in that gap used to be reported as a failed
        # segment that had in fact never run.  The segment's LOG is the evidence of
        # a launch: NAMD creates it on spawn, so no log means no attempt.
        if not _latest_segment_log(package_dir, active.name).exists():
            active.status = "pending"
            job.status = MdStatus.running
            job.error = (
                f"Interrupted before {active.name} started; it will run on resume."
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

    reconcile_manifest = json.loads(manifest_path.read_text())
    graphene_only = bool(
        reconcile_manifest.get("graphene_only")
        or (reconcile_manifest.get("charge_audit") or {}).get("graphene_only")
        or (reconcile_manifest.get("graphene_nanopore") or {}).get("control")
        == "graphene_only"
    )
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
    if not _jsonl_has_segment(health_path, active.name) and _segment_outputs_complete(
        output_dir, active.name
    ):
        hresult = (
            HealthCheckResult(
                passed=True,
                blocking=False,
                reason="DNA structural metrics are not applicable to a graphene-only control.",
            )
            if graphene_only
            else run_health_check(
                package_dir,
                active.name,
                job.name_stem,
                min_c1_paired=spec.min_c1_paired,
                min_wc_ref_relative=spec.min_wc_ref_relative,
            )
        )
        append_health_jsonl(output_dir, active.name, active.stage, hresult)
        job.health_samples.append(
            MdHealthSample.from_result(
                hresult, active.stage, active.name, blocking=hresult.blocking
            )
        )
        # Health is advisory only — a below-threshold checkpoint warns and is
        # flagged in the UI, but never stops the run.
        if not hresult.passed:
            logger.warning(
                "[%s] Health warning after %s (below threshold, continuing): %s",
                job.job_id,
                active.name,
                hresult.reason or hresult.error,
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
    dirs.sort(
        key=lambda d: 0 if "cuda" in os.path.basename(d).lower() else 1
    )  # stable: CUDA first
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
        candidate
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK)
        else None
    )


def find_namd(prefer_cpu: bool = False) -> str:
    """Return the first usable NAMD3 binary path.

    Resolution order:
      1. ``$NADOC_NAMD_BIN`` — explicit override (absolute path or PATH-resolvable name).
      2. ``namd3`` on ``$PATH``.
      3. Conventional ``~/Applications`` installs (CUDA/GPU build preferred over CPU).

    ``prefer_cpu=True`` returns the first NON-CUDA (multicore CPU) build instead —
    required for GBIS implicit solvent, which is unsupported on the NAMD 3 CUDA
    nonbonded kernel (it crashes in ``buildTileLists``).  Raises if no CPU build is
    installed, since silently using the CUDA build would just crash again.

    See ``docs/namd_setup.md`` for install guidance (WSL + GPU notes included).
    """
    override = os.environ.get("NADOC_NAMD_BIN", "").strip()
    candidates = ([override] if override else []) + _namd_candidates()
    resolved = [f for f in (_resolve_namd(c) for c in candidates) if f]
    if not resolved:
        raise RuntimeError(
            "NAMD3 not found.  Set $NADOC_NAMD_BIN to the namd3 binary, install to "
            "~/Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3, or add namd3 to "
            "PATH.  See docs/namd_setup.md."
        )
    if prefer_cpu:
        for found in resolved:
            if not namd_is_cuda_build(found):
                return found
        raise RuntimeError(
            "Implicit-solvent (GBIS) needs a CPU (non-CUDA) NAMD build — GBIS is "
            "unsupported on the NAMD 3 CUDA kernel (crashes in buildTileLists).  "
            "Install the multicore build, e.g. "
            "~/Applications/NAMD_3.0.2_Linux-x86_64-multicore/namd3."
        )
    return resolved[0]


def job_wants_cpu(protocol: Optional[str], devices: Optional[str]) -> bool:
    """True if a job must/should run on the CPU (non-CUDA) NAMD build.

    - GBIS implicit solvent is CPU-only on NAMD 3 CUDA (crashes buildTileLists), so
      it ALWAYS forces CPU regardless of the device string.
    - Otherwise the user's Compute choice drives it: ``devices`` of ``"cpu"``/``"none"``
      means CPU; GPU indices (``"0"``, ``"0,1"``, or empty = auto) mean the CUDA build.
    """
    from backend.core.md_protocols import IMPLICIT_GBIS_PROTOCOL  # noqa: PLC0415

    if protocol == IMPLICIT_GBIS_PROTOCOL:
        return True
    return (devices or "").strip().lower() in ("cpu", "none")


def resolve_namd_launch(
    protocol: Optional[str], devices: Optional[str]
) -> tuple[str, str]:
    """Pick the NAMD binary + ``+devices`` string for a job's compute target.

    Robust across every install combo ("works on all versions"):
      • CPU wanted (GBIS or Compute=CPU) → the ``-multicore`` build, no ``+devices``.
        If only a CUDA build exists: GBIS raises (it truly cannot use CUDA); an
        explicit-solvent CPU request degrades to the CUDA build (best effort).
      • GPU wanted → the CUDA build + the requested devices.  On a CPU-only machine
        (no CUDA build) it degrades to the multicore build with no ``+devices``.

    Returns ``(namd_bin, run_devices)``.
    """
    want_cpu = job_wants_cpu(protocol, devices)
    if want_cpu:
        try:
            return find_namd(prefer_cpu=True), ""
        except RuntimeError:
            # GBIS truly cannot use CUDA → surface the install guidance.
            if job_wants_cpu(protocol, None):
                raise
            # Explicit-solvent CPU request but no CPU build installed: best-effort GPU.
            return find_namd(), "0"
    namd_bin = find_namd()  # CUDA-first ordering
    if not namd_is_cuda_build(namd_bin):
        return namd_bin, ""  # CPU-only machine: a GPU request degrades cleanly
    return namd_bin, devices or ""


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
        out = subprocess.run([namd_bin], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return "CUDA" in (out.stdout + out.stderr)


# ── NAMD CUDA tile-list bug: pre-flight probe ────────────────────────────────
#
# NAMD 3.0.2's CUDA `buildTileLists` kernel sizes its loop from a CPU-side count
# of tile lists but fills the array from a GPU-side count.  When the CPU count is
# larger the tail of `tileLists` is never written; the kernel reads those zeroed
# entries, derives patch index 0 / offset 0 from them, and indexes `boundingBoxes`
# far past its end -> cudaErrorIllegalAddress on the very FIRST step (minimize or
# dynamics).  `boundingBoxes` has no bounds check in that kernel.
#
# The failure is deterministic per package but is NOT a function of the patch grid:
# the identical grid (26x3x34) crashes at 380k atoms and runs at 611k, because what
# the kernel actually indexes is the TILE-LIST count, which depends on atom density
# too.  A closed-form predictor is therefore unsound (verified: it mispredicts
# non-uniform-density carved-shell systems).  So we settle it empirically — run one
# minimization cycle on the GPU and look at the log.  ~5-15 s against a multi-hour
# production run.  NAMD 3.1 does NOT fix this upstream.  See LESSONS K2.

GPU_PROBE_CACHE = ".gpu_tilelist_probe.json"
_TILELIST_CRASH_PAT = re.compile(r"buildTileLists", re.IGNORECASE)
GPU_PROBE_TIMEOUT_S = 600.0


def _write_probe_conf(min_conf: Path, probe_conf: Path, out_stem: str) -> None:
    """Copy *min_conf* into *probe_conf*, shortened to one minimization cycle and
    writing its output to *out_stem* so the real ``output/`` is never touched.

    NAMD requires the step count to be a multiple of ``stepspercycle``, so the probe
    runs exactly one cycle (the crash fires on the first step regardless).
    """
    text = min_conf.read_text()
    m = re.search(r"^\s*stepspercycle\s+(\d+)", text, re.IGNORECASE | re.MULTILINE)
    cycle = int(m.group(1)) if m else 20
    # Adaptive configs contain a Tcl loop rather than a literal ``minimize N``.  The
    # tile-list probe must never execute that real loop: replace it wholesale with the
    # same one-cycle probe used for legacy configs.
    text = re.sub(
        r"^# NADOC_ADAPTIVE_MIN_BEGIN$.*?^# NADOC_ADAPTIVE_MIN_END$",
        f"minimize           {cycle}",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    text = re.sub(
        r"^(\s*minimize\s+)\d+",
        rf"\g<1>{cycle}",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    text = re.sub(
        r"^(\s*outputName\s+)\S+",
        rf"\g<1>{out_stem}",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    probe_conf.write_text(text)


def gpu_tilelist_probe(
    package_dir: Path,
    min_name: str,
    namd_bin: str,
    devices: str,
    threads: Optional[int] = None,
) -> bool:
    """True if this package is SAFE to run on the CUDA build.

    Runs one minimization cycle on the GPU and reports whether NAMD survived the
    tile-list build.  The verdict is cached in the package (the geometry can't
    change under a prepared package), so a resume never re-pays for it.

    Returns True (assume safe) if the probe itself can't run — a probe failure must
    never be what stops a job from launching.
    """
    cache = package_dir / GPU_PROBE_CACHE
    if cache.exists():
        try:
            return bool(json.loads(cache.read_text())["gpu_safe"])
        except (ValueError, KeyError, OSError):
            pass  # unreadable cache → just re-probe

    min_conf = package_dir / f"{min_name}.conf"
    if not min_conf.exists():
        return True

    probe_conf = package_dir / "_gpu_probe.conf"
    probe_stem = "_gpu_probe_out"
    probe_log = package_dir / "_gpu_probe.log"
    try:
        _write_probe_conf(min_conf, probe_conf, probe_stem)
        cmd = [namd_bin, f"+p{threads or default_threads()}", "+setcpuaffinity"]
        if devices:
            cmd += ["+devices", devices]
        cmd.append(probe_conf.name)
        out = subprocess.run(
            cmd,
            cwd=package_dir,
            capture_output=True,
            text=True,
            timeout=GPU_PROBE_TIMEOUT_S,
        )
        log = out.stdout + out.stderr
        probe_log.write_text(log)
        safe = not _TILELIST_CRASH_PAT.search(log)
    except (OSError, subprocess.SubprocessError):
        return True  # can't probe → don't block the job
    finally:
        for junk in (probe_conf, *package_dir.glob(f"{probe_stem}*")):
            junk.unlink(missing_ok=True)

    try:
        cache.write_text(json.dumps({"gpu_safe": safe}))
    except OSError:
        pass
    return safe


# ── GPU-resident pinned-host pre-flight ──────────────────────────────────────
#
# NADOC's "fast" segments bake in `GPUresident on` (+ HMR + rigidBonds all + 4 fs).
# GPU-resident mode pins a big host buffer via cudaMallocHost, and a host's pinned pool
# can be far smaller than its free RAM — this WSL box caps it at 1.0 GB with 15 GB free.
# Above ~800k atoms NAMD then dies at segment START:
#   FATAL ERROR: CUDA error cudaMallocHost(...) in CudaUtils.C, allocate_host_T, line 88
# (measured: 756k atoms OK, 971k fails; GT_corner_v2's 1.44M-atom relax package fails).
#
# The ceiling is a property of the HOST, not of NAMD or the design, so it is not
# predictable from atom count alone across machines (the other computer has a different
# pinned pool).  Settle it empirically, exactly like the tile-list probe: run one cycle
# of the fast conf and look at the log.  See LESSONS K6.

GPU_RESIDENT_PROBE_CACHE = ".gpu_resident_probe.json"
# Every way a GPU-resident run is known to die on THIS host / THIS package:
#   • cudaMallocHost / cudaHostAlloc — pinned host pool too small (K6, above).
#   • "Low global CUDA exclusion count" — NAMD sizes its GPU tile/exclusion buffers
#     from the cell-AVERAGE density, so a cell containing vacuum (a water-shell carve
#     on a concave design) under-counts exclusions and dies at step 0.  Measured: a
#     22%-water-filled cell finds 241926 of 276956 exclusions; even 80% fill fails;
#     ~90%+ is needed.  md_protocols now refuses to emit GPUresident on a carved
#     package at all, so this pattern is a backstop for anything that slips through.
_GPU_RESIDENT_FAIL_PAT = re.compile(
    r"cudaMallocHost|cudaHostAlloc|Low global CUDA exclusion count", re.IGNORECASE
)


def _has_gpu_resident(conf: Path) -> bool:
    try:
        return bool(
            re.search(
                r"^[ \t]*GPUresident\b[ \t]+on",
                conf.read_text(),
                re.IGNORECASE | re.MULTILINE,
            )
        )
    except OSError:
        return False


def gpu_resident_probe(
    package_dir: Path,
    conf_name: str,
    namd_bin: str,
    devices: str,
    threads: Optional[int] = None,
    seed_stem: Optional[str] = None,
) -> bool:
    """True if this package can actually run GPU-resident on THIS host.

    Runs one pairlist cycle of the fast conf and reports whether NAMD's GPU-resident
    setup actually stands up (pinned host buffers AND the exclusion/tile-list build).
    Verdict cached in the package.  Fails OPEN (a probe that can't run never blocks a
    job) — but ONLY when the probe genuinely could not execute, never because NAMD
    died of something we forgot to look for.

    ``seed_stem`` is the stem whose ``output/<stem>.coor/.vel/.xsc`` the probe restarts
    from — pass the MINIMISATION stem and call this only after minimisation has run.
    Both alternatives are traps that silently pass a broken package:
      • Leaving the fast conf's own ``binCoordinates`` (a *later* segment's output, not
        yet written) makes NAMD abort at startup — "Unable to open extended system
        file" — before it ever touches the GPU.
      • Seeding from the raw PDB makes the ideal-B-DNA build clashes blow the
        integrator up at step 1 ("Atoms moving too fast") BEFORE the GPU-resident
        exclusion check fires.
    Only minimised coordinates actually exercise the thing being probed.
    """
    cache = package_dir / GPU_RESIDENT_PROBE_CACHE
    if cache.exists():
        try:
            return bool(json.loads(cache.read_text())["gpu_resident_ok"])
        except (ValueError, KeyError, OSError):
            pass

    conf = package_dir / f"{conf_name}.conf"
    if not conf.exists():
        return True

    probe_conf = package_dir / "_gpures_probe.conf"
    probe_stem = "_gpures_probe_out"
    try:
        text = conf.read_text()
        m = re.search(r"^\s*stepspercycle\s+(\d+)", text, re.IGNORECASE | re.MULTILINE)
        cycle = int(m.group(1)) if m else 20
        text = re.sub(
            r"^(\s*run\s+)\d+",
            rf"\g<1>{cycle}",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        text = re.sub(
            r"^(\s*(?:outputName|dcdFile|xstFile)\s+)\S+",
            lambda mm: f"{mm.group(1)}{probe_stem}",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        # Re-seed from the minimised state, which exists and is clash-free.
        if seed_stem:
            for key, ext in (
                ("binCoordinates", "coor"),
                ("binVelocities", "vel"),
                ("extendedSystem", "xsc"),
            ):
                text = re.sub(
                    rf"^(\s*{key}\s+)\S+",
                    rf"\g<1>output/{seed_stem}.{ext}",
                    text,
                    flags=re.IGNORECASE | re.MULTILINE,
                )
        probe_conf.write_text(text)

        cmd = [namd_bin, f"+p{threads or default_threads()}", "+setcpuaffinity"]
        if devices:
            cmd += ["+devices", devices]
        cmd.append(probe_conf.name)
        out = subprocess.run(
            cmd,
            cwd=package_dir,
            capture_output=True,
            text=True,
            timeout=GPU_PROBE_TIMEOUT_S,
        )
        log = out.stdout + out.stderr
        (package_dir / "_gpures_probe.log").write_text(log)
        ok = not _GPU_RESIDENT_FAIL_PAT.search(log) and "FATAL ERROR" not in log
    except (OSError, subprocess.SubprocessError):
        return True
    finally:
        for junk in (probe_conf, *package_dir.glob(f"{probe_stem}*")):
            junk.unlink(missing_ok=True)

    try:
        cache.write_text(json.dumps({"gpu_resident_ok": ok}))
    except OSError:
        pass
    return ok


def retarget_settle_restraints(
    package_dir: Path,
    min_coor: Path,
    job_id: str = "",
) -> bool:
    """Re-point the settle stage's restraint reference at the minimised coordinates.

    Returns True if the file was rewritten.  Best-effort: a package without a settle
    stage (carved/NVT, or prepped before the stage existed) simply has no such file, and
    any failure leaves the shipped build-pose reference in place rather than failing the
    job.  See the call site for why the build pose is not good enough.
    """
    from backend.core.md_protocols import (  # noqa: PLC0415
        SOLUTE_RESTRAINT_PDB,
        write_declashed_pdb,
    )

    ref = package_dir / SOLUTE_RESTRAINT_PDB
    if not ref.exists() or not min_coor.exists():
        return False
    try:
        n = write_declashed_pdb(min_coor, ref, ref)
    except Exception as exc:
        logger.error(
            "[%s] Could not re-reference %s to the minimised coordinates (%s) — the "
            "settle stage will restrain to the build pose instead.",
            job_id,
            SOLUTE_RESTRAINT_PDB,
            exc,
        )
        return False
    logger.info(
        "[%s] Settle restraints re-referenced to the minimised structure (%d atoms).",
        job_id,
        n,
    )
    return True


def downgrade_gpu_resident_confs(package_dir: Path, job_id: str = "") -> list[str]:
    """Rewrite every GPU-resident conf in *package_dir* to a runnable non-GPU-resident
    form (GPUresident dropped, timestep halved, step counts + output cadence doubled so
    the simulated time and frame count are preserved).  The original is kept as
    ``<name>.conf.gpuresident``.  Returns the segment names rewritten.
    """
    from backend.core.md_protocols import downgrade_gpu_resident  # noqa: PLC0415

    rewritten: list[str] = []
    for conf in sorted(package_dir.glob("*.conf")):
        if conf.name.startswith("_") or not _has_gpu_resident(conf):
            continue
        original = conf.read_text()
        conf.with_suffix(".conf.gpuresident").write_text(original)
        conf.write_text(downgrade_gpu_resident(original))
        rewritten.append(conf.stem)
    if rewritten:
        logger.warning(
            "[%s] GPU-resident unavailable on this host (pinned-host limit) — rewrote "
            "%d segment(s) to GPUresident off + half timestep (same simulated time): %s",
            job_id,
            len(rewritten),
            ", ".join(rewritten),
        )
    return rewritten


# ── GPU-resident fallback: ask the user instead of silently downgrading ────────
#
# Default policy is "ask": a capable GPU is assumed wanted, so if the fastest mode
# can't run we PAUSE and present a decision rather than quietly halving throughput.
# NADOC_GPU_FALLBACK=auto_offload restores the old silent-downgrade for unattended
# runs. (With a resident-capable NAMD build pinned, this path rarely fires at all.)


def gpu_fallback_policy() -> str:
    """ "ask" (default — pause + decision) or "auto_offload" (silent downgrade)."""
    val = os.environ.get("NADOC_GPU_FALLBACK", "").strip().lower()
    return "auto_offload" if val == "auto_offload" else "ask"


def build_gpu_fallback_decision(fux) -> dict:
    """Build the serialisable Gate-B decision payload the frontend renders as a modal.

    ``fux`` is a :class:`md_vram.FailureUX`. The offer is always "run the slower GPU
    mode or cancel"; ``retry_hint`` flags the case a newer NAMD build would fix (so the
    UI can add "…or install a newer NAMD build"). Wall-clock estimates are left to the
    frontend (it has the job's ns/day) — the backend does not guess time here.
    """
    return {
        "gate": "gpu_resident",
        "severity": fux.severity,  # "decision"
        "title": fux.title,
        "message": fux.message,
        "technical_reason": fux.technical_reason,  # logs/tooltip only, never headline
        "retry_hint": bool(fux.retry_other_binary),
        "degrade_target": fux.degrade_target,  # "offload"
        "checks": [
            {"label": "GPU found", "ok": True},
            {"label": "System fits in memory", "ok": True},
            {"label": "Structure minimized cleanly", "ok": True},
            {"label": "Fastest GPU mode started", "ok": False},
        ],
        "options": [
            {"id": "offload", "label": "Run in slower GPU mode", "primary": True},
            {"id": "cancel", "label": "Cancel", "primary": False},
        ],
    }


def handle_resident_probe_failure(
    job: MdJob, package_dir: Path, workspace_dir: Path
) -> bool:
    """React to a failed GPU-resident pre-flight. Returns True to PROCEED with the run,
    False to PAUSE it awaiting the user's decision (caller must then exit cleanly).

    "ask" (default): classify the probe log, stash a Gate-B decision on the job, set
    status=paused, and return False. "auto_offload": downgrade the confs and proceed
    (the legacy silent behaviour), returning True.
    """
    # Per-job policy (from the launch toggle, stored in prep_params) overrides the env
    # default — so "Prefer fastest GPU mode" is a real per-run setting, not just global.
    policy = (job.prep_params or {}).get("gpu_fallback_policy") or gpu_fallback_policy()
    if policy == "auto_offload":
        downgrade_gpu_resident_confs(package_dir, job.job_id)
        return True
    fux = describe_failure_file(package_dir / "_gpures_probe.log")
    job.decision = build_gpu_fallback_decision(fux)
    job.status = MdStatus.paused
    job.save(workspace_dir)
    logger.info(
        "[%s] GPU-resident unavailable (%s) — paused for user decision (Gate B).",
        job.job_id,
        fux.kind,
    )
    return False


def build_cpu_reroute_decision(namd_cpu_available: bool) -> dict:
    """Gate B2: the CUDA tile-list bug hit this geometry — CPU build, or cancel?

    Same shape as :func:`build_gpu_fallback_decision`, because it is the same kind of
    question: a pre-flight found the fast path cannot start, and the fallback is much
    slower.  It used to reroute to the CPU build silently, with only a log line — roughly
    a 12x slowdown that a user could discover only by watching the ETA.
    """
    return {
        "gate": "cpu_reroute",
        "severity": "decision",
        "title": "This structure hits a known NAMD GPU bug",
        "message": (
            "NAMD's CUDA build crashes while building its neighbour lists on this "
            "geometry (a known bug in 3.0.2's buildTileLists). The CPU build runs it "
            "correctly, but roughly 12x slower. Nothing about the physics changes."
            if namd_cpu_available
            else "NAMD's CUDA build crashes while building its neighbour lists on this "
            "geometry, and no CPU (-multicore) build is installed to fall back to. "
            "Running anyway will crash at the first segment."
        ),
        "technical_reason": "gpu_tilelist_probe failed (illegal memory access in "
        "buildTileLists)",
        "retry_hint": True,
        "degrade_target": "cpu",
        "checks": [
            {"label": "GPU found", "ok": True},
            {"label": "System fits in memory", "ok": True},
            {"label": "CUDA neighbour lists built", "ok": False},
            {"label": "CPU build available", "ok": bool(namd_cpu_available)},
        ],
        "options": (
            [
                {
                    "id": "cpu",
                    "label": "Run on the CPU build (~12x slower)",
                    "primary": True,
                },
                {"id": "cancel", "label": "Cancel", "primary": False},
            ]
            if namd_cpu_available
            else [{"id": "cancel", "label": "Cancel", "primary": True}]
        ),
    }


def resolve_gpu_decision(job: MdJob, choice: str, workspace_dir: Path) -> MdJob:
    """Apply the user's Gate-B choice to a paused job (caller then starts it if resumed).

    ``"offload"`` — downgrade the resident confs to the slower GPU mode and re-queue the
    job (resume then SKIPS the probe, since no conf still asks for GPU-resident).
    ``"cancel"`` — clean-stop the job. Any other choice is rejected. Clears ``decision``.
    """
    if choice == "offload":
        downgrade_gpu_resident_confs(job.package_dir(workspace_dir), job.job_id)
        job.decision = None
        job.status = MdStatus.running  # runner flips it on relaunch; resume skips probe
        job.error = None
    elif choice == "cpu":
        # Gate B2. Recorded on the job so the reroute is a CHOICE with a trace, not a
        # silent substitution the user can only infer from the ETA.
        pp = dict(job.prep_params or {})
        pp["cpu_reroute_accepted"] = True
        job.prep_params = pp
        job.decision = None
        job.status = MdStatus.running
        job.error = None
    elif choice == "cancel":
        apply_user_stop(job)
        job.decision = None
    else:
        raise ValueError(f"unknown gpu-decision choice: {choice!r}")
    job.save(workspace_dir)
    return job


# ── In-flight health sampling ─────────────────────────────────────────────────
#
# Health used to be computed ONLY after a segment finished.  A relaxation ladder has 12
# segments, so its health bar fills in as it goes — but a PRODUCTION run is ONE segment,
# so the bar stayed empty for the entire run and produced exactly one sample at the very
# end.  Measured on a 200 ns / 50M-step 4 fs production: 1 sample after ~13 hours.
#
# That is not just a cosmetic gap.  The single end-point sample read c1=0.850 / wc=0.641
# (FAILED), while a probe of the same run at 90 ns read c1=0.950 / wc=0.744 (passed) —
# the structure degraded over the run and nothing recorded the trend.
#
# `run_health_check` reads output/<segment>.dcd, which NAMD writes incrementally, so the
# data was there all along.  Measured cost on a live 2.4 GB DCD: ~13 s.
_INFLIGHT_HEALTH_INTERVAL_S = float(
    os.environ.get("NADOC_INFLIGHT_HEALTH_INTERVAL_S", "300")
)
# Skip the last frames: NAMD may be mid-write at the DCD tail while we read it.
_INFLIGHT_HEALTH_SAFE_BACK = 2
# How soon the FIRST in-flight probe runs, so the Health card fills in promptly instead
# of showing nothing for a whole interval at every segment start.
_INFLIGHT_HEALTH_FIRST_S = float(os.environ.get("NADOC_INFLIGHT_HEALTH_FIRST_S", "30"))


def _fail_on_disk_abort(
    job, spec, idx: int, package_dir: Path, workspace_dir: Path
) -> None:
    """Mark a job failed because the disk guard stopped it.  Shared by the spawned and
    adopted segment paths so an adopted run reports the abort identically."""
    fb = free_bytes(package_dir)
    logger.error(
        "[%s] Disk guard aborted %s: %.1f GB free", job.job_id, spec.name, fb / GiB
    )
    if idx < len(job.segments):
        job.segments[idx].status = "failed"
    job.status = MdStatus.failed
    job.failure_kind = "disk_full"
    job.error = (
        f"Stopped: free disk fell below {ABORT_MIN_FREE_BYTES / GiB:.0f} GB "
        f"while running {spec.name} ({fb / GiB:.1f} GB free). "
        "Free up space (delete old jobs or change their directory), then resume."
    )
    job.save(workspace_dir)


def _note_health_probe(job, workspace_dir: Path, **fields) -> None:
    """Merge ``fields`` into ``job.health_probe`` and persist.

    This is what lets the Health card explain an absent metric instead of spinning on
    it forever: the card reads ``enabled`` / ``last_at`` / ``last_error`` / ``reason``
    and decides between "still computing", "will not be computed" and "failed".
    Never raises — bookkeeping must not be able to disturb the run it describes.
    """
    try:
        probe = dict(job.health_probe or {})
        probe.setdefault("enabled", True)
        probe.setdefault("interval_s", _INFLIGHT_HEALTH_INTERVAL_S)
        probe.setdefault("started_at", None)  # when this segment's probe began watching
        probe.setdefault(
            "last_tick_at", None
        )  # last time the probe RAN (sample or not)
        probe.setdefault("last_at", None)  # last time it produced a SAMPLE
        probe.setdefault("last_error", None)
        probe.setdefault("reason", None)
        if fields.pop("adopted", False):
            # A durable fact about this segment, not a transient status: recorded on its
            # own key so the tick factory's counter reset does not wipe it, and so it
            # never masquerades as the reason a metric is missing (it is not — an
            # adopted run samples normally now).
            probe["adopted"] = True
        probe.update(fields)
        job.health_probe = probe
        job.save(workspace_dir)
    except Exception:  # noqa: BLE001
        logger.debug("[%s] health_probe bookkeeping failed", job.job_id, exc_info=True)


def _make_inflight_health_tick(
    job, spec, package_dir: Path, output_dir: Path, workspace_dir: Path
):
    """Periodic callback that appends a health sample WHILE a segment runs.

    Returns None when sampling is disabled.  The callback is deliberately total: any
    failure is logged and swallowed, because a monitoring probe must never be able to
    disturb (let alone kill) the run it is watching.
    """
    if _INFLIGHT_HEALTH_INTERVAL_S <= 0:
        _note_health_probe(
            job,
            workspace_dir,
            enabled=False,
            reason="in-flight health sampling is disabled "
            "(NADOC_INFLIGHT_HEALTH_INTERVAL_S=0)",
        )
        return None
    # Publish the probe's existence up front, so the card can distinguish "a sample is
    # coming" from "nothing will ever sample this" before the first tick has run.
    #
    # `started_at` is when THIS segment's probe began watching, and the counters are
    # reset with it.  The job's own `created_at` is not a usable clock here: a resumed
    # run can be many hours old while its probe is seconds old, which would make any
    # staleness test fire instantly on resume.
    _note_health_probe(
        job,
        workspace_dir,
        enabled=True,
        interval_s=_INFLIGHT_HEALTH_INTERVAL_S,
        started_at=time.time(),
        last_tick_at=None,
        last_at=None,
        last_error=None,
        reason=None,
    )
    # The FIRST probe fires early, then the loop settles to the full interval.  Waiting
    # a whole interval meant the Health card sat blank for five minutes at the start of
    # every segment even when everything was working.
    state = {
        "next_at": time.time()
        + min(_INFLIGHT_HEALTH_FIRST_S, _INFLIGHT_HEALTH_INTERVAL_S),
        "busy": False,
    }

    async def _tick():
        now = time.time()
        # `busy` guards the case where a check outlives the interval (a very large DCD):
        # without it the samples would pile up and compound the I/O they are competing
        # with.  Skipping is always safe — the next tick takes it.
        if state["busy"] or now < state["next_at"]:
            return
        dcd = _latest_segment_dcd(output_dir, spec.name)
        if not dcd.exists() or dcd.stat().st_size == 0:
            _note_health_probe(
                job,
                workspace_dir,
                last_tick_at=time.time(),
                last_error=None,
                reason="waiting for the first trajectory frames",
            )
            return
        state["busy"] = True
        try:
            hresult = await asyncio.to_thread(
                run_health_check,
                package_dir,
                spec.name,
                job.name_stem,
                min_c1_paired=spec.min_c1_paired,
                min_wc_ref_relative=spec.min_wc_ref_relative,
                safe_back=_INFLIGHT_HEALTH_SAFE_BACK,
                # The per-frame series is discarded on this path (an in-flight probe
                # writes no health.jsonl record), so walking the whole trajectory is
                # pure cost — and this runs inline in the disk guard's poll loop.
                per_frame=False,
            )
            if hresult.error:
                # Record WHY there is no sample.  "Too few frames yet" is normal at the
                # start of a segment and must not read as a failure; anything else is
                # one, and the card says so instead of spinning on it forever.
                _note_health_probe(
                    job,
                    workspace_dir,
                    last_tick_at=time.time(),
                    last_error=None if hresult.not_ready else hresult.error,
                    reason=(
                        "waiting for the first trajectory frames"
                        if hresult.not_ready
                        else None
                    ),
                )
                return
            job.health_samples.append(
                MdHealthSample.from_result(
                    # Advisory by construction: an in-flight probe must never be able to
                    # stop the run it is watching.
                    hresult,
                    spec.stage,
                    spec.name,
                    blocking=False,
                )
            )
            _note_health_probe(
                job,
                workspace_dir,
                last_at=time.time(),
                last_tick_at=time.time(),
                last_error=hresult.diagnostics_error,
                reason=None,
            )
            logger.info(
                "[%s] in-flight health %s: c1=%.3f wc=%.3f",
                job.job_id,
                spec.name,
                hresult.c1_paired_fraction or 0.0,
                hresult.wc_ref_relative_fraction or 0.0,
            )
        finally:
            state["busy"] = False
            state["next_at"] = time.time() + _INFLIGHT_HEALTH_INTERVAL_S

    return _tick


def soften_stability_confs(
    package_dir: Path, segments: list, from_idx: int, job_id: str = ""
) -> list[str]:
    """Rewrite the failing segment + every LATER hard (``rigidBonds all``) segment to the
    soft integrator (``rigidBonds none`` + 1 fs), so a RATTLE / instability blow-up on a
    strained seed is rescued by re-running the rest of the ladder gently instead of
    dead-ending.  The original is kept as ``<name>.conf.hard``.  Returns the segment names
    actually rewritten (a conf already soft is left untouched → not in the list)."""
    from backend.core.md_protocols import soften_conf_for_stability  # noqa: PLC0415

    rewritten: list[str] = []
    for seg in segments[from_idx:]:
        conf = package_dir / f"{seg.name}.conf"
        if not conf.exists():
            continue
        original = conf.read_text()
        softened = soften_conf_for_stability(original)
        if softened == original:
            continue  # already soft (rigidBonds none) — nothing to do
        conf.with_suffix(".conf.hard").write_text(original)
        conf.write_text(softened)
        rewritten.append(seg.name)
    if rewritten:
        logger.warning(
            "[%s] instability rescue — softened %d segment(s) to rigidBonds none + 1 fs: %s",
            job_id,
            len(rewritten),
            ", ".join(rewritten),
        )
    return rewritten


def _clear_segment_restart_files(output_dir: Path, segment_name: str) -> None:
    """Remove a crashed segment's partial NAMD checkpoint so it restarts FRESH from the
    previous stage's coordinates (via its conf's ``binCoordinates``) instead of resuming
    mid-segment from the blown-up state.  ``_resume_step`` keys off ``.restart.xsc``, so
    clearing the ``.restart.*`` set forces a clean re-run."""
    for pat in (f"{segment_name}.restart.*", f"{segment_name}.cont*.dcd"):
        for p in output_dir.glob(pat):
            try:
                p.unlink()
            except OSError:
                pass


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
    on_tick=None,
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
            start_new_session=True,  # own process group for clean kill
        )
        pid = proc.pid
        if job_id:
            _ACTIVE_PIDS[job_id] = pid
        if on_spawn:
            try:
                on_spawn(pid)
            except Exception:
                pass  # noqa: E722,S110 — persistence must never break the run
        try:
            rc = await wait_proc_with_disk_guard(
                proc, package_dir, kill=_kill_process_group, on_tick=on_tick
            )
        except asyncio.CancelledError:
            _kill_process_group(pid)
            raise
        finally:
            if job_id:
                _ACTIVE_PIDS.pop(job_id, None)
            if on_spawn:
                try:
                    on_spawn(None)
                except Exception:
                    pass  # noqa: E722,S110
    return rc, pid


def _kill_process_group(pid: int, timeout: float = 15.0) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, OSError):
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.killpg(os.getpgid(pid), 0)  # check if still alive
        except (ProcessLookupError, OSError):
            return
        time.sleep(0.25)
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


# ── Metrics jsonl helper ──────────────────────────────────────────────────────


def _append_metrics_jsonl(
    output_dir: Path, segment_name: str, stage: str, log_path: Path
) -> None:
    if not log_path.exists():
        return
    m = parse_namd_log(log_path)
    record = {
        "wall_time": time.time(),
        "segment": segment_name,
        "stage": stage,
        "ns_per_day": m.ns_per_day,
        "temperature_k": m.temperature_k,
        "temperature_avg_k": m.temperature_avg_k,
        "pressure_bar": m.pressure_bar,
        "pressure_avg_bar": m.pressure_avg_bar,
        "gpressure_bar": m.gpressure_bar,
        "gpressure_avg_bar": m.gpressure_avg_bar,
        "volume_ang3": m.volume_ang3,
        "total_energy_kcal": m.total_energy_kcal,
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
                "next stage may fail to restart",
                ext,
                completed_name,
            )
            continue
        for skip in skipped_names:
            shutil.copy2(src, output_dir / f"{skip}.{ext}")
            shutil.copy2(src, output_dir / f"{skip}.restart.{ext}")


async def run_job(job: MdJob, workspace_dir: Path) -> None:
    """Async coroutine — runs until completion, failure, or cancellation."""
    package_dir = job.package_dir(workspace_dir)
    output_dir = package_dir / "output"
    output_dir.mkdir(exist_ok=True)

    logger.info("[%s] run_job starting; package_dir=%s", job.job_id, package_dir)

    # Pick the NAMD binary + devices for the job's Compute target.  GBIS forces the
    # CPU build (unsupported on the NAMD 3 CUDA kernel — buildTileLists crash);
    # otherwise Compute=CPU (devices "cpu") uses it too, and GPU uses the CUDA build.
    want_cpu = job_wants_cpu(job.protocol, job.devices)
    try:
        namd_bin, run_devices = resolve_namd_launch(job.protocol, job.devices)
        logger.info(
            "[%s] NAMD binary: %s%s",
            job.job_id,
            namd_bin,
            " (CPU build)" if want_cpu else "",
        )
    except RuntimeError as exc:
        logger.error("[%s] NAMD not found: %s", job.job_id, exc)
        job.status = MdStatus.failed
        job.error = str(exc)
        job.save(workspace_dir)
        return

    # Load manifest
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.exists():
        logger.error("[%s] manifest.json not found at %s", job.job_id, manifest_path)
        job.status = MdStatus.failed
        job.error = "manifest.json not found in package_dir"
        job.save(workspace_dir)
        return

    manifest = json.loads(manifest_path.read_text())
    graphene_only = bool(
        manifest.get("graphene_only")
        or (manifest.get("charge_audit") or {}).get("graphene_only")
        or (manifest.get("graphene_nanopore") or {}).get("control") == "graphene_only"
    )
    min_name = manifest["minimization"]["name"]
    _, segments = segments_from_manifest(manifest_path)
    # Jobs prepared before job.minimization existed get their timeline row here, so an
    # already-queued run does not have to be rebuilt to show its minimisation.
    if job.minimization is None:
        job.minimization = minimization_status(manifest)
    logger.info(
        "[%s] Loaded manifest: %d segments, min=%s", job.job_id, len(segments), min_name
    )

    # GPU pre-flight.  NAMD 3.0.2's CUDA buildTileLists kernel dies with an illegal
    # memory access on the first step for certain (patch-grid × atom-density)
    # geometries — deterministic, but not predictable from the patch grid alone.
    # Settle it empirically (~5-15 s, cached in the package) and route a genuinely
    # unsafe geometry to the CPU build instead of letting it crash.  See LESSONS K2.
    if not want_cpu and namd_is_cuda_build(namd_bin):
        # blocking subprocess → off the event loop, or the whole API stalls on it
        gpu_safe = await asyncio.to_thread(
            gpu_tilelist_probe,
            package_dir,
            min_name,
            namd_bin,
            run_devices,
            job.threads,
        )
        if not gpu_safe:
            # ASK, do not reroute.  The CPU build is ~12x slower; swapping to it behind
            # the user's back changed the run's cost by an order of magnitude with only a
            # log line to show for it.  Same Gate-B contract as the GPU-resident probe:
            # a previously-accepted reroute (or the auto policy) proceeds without asking.
            try:
                cpu_bin = find_namd(prefer_cpu=True)
            except RuntimeError:
                cpu_bin = None
            already = bool((job.prep_params or {}).get("cpu_reroute_accepted"))
            policy = (job.prep_params or {}).get(
                "gpu_fallback_policy"
            ) or gpu_fallback_policy()
            if already or policy == "auto_offload":
                if cpu_bin:
                    namd_bin, run_devices = cpu_bin, ""
                    logger.info(
                        "[%s] NAMD binary (rerouted, accepted): %s (CPU build)",
                        job.job_id,
                        namd_bin,
                    )
                else:
                    logger.error(
                        "[%s] No CPU NAMD build installed — staying on the GPU build, "
                        "which will crash on this geometry.",
                        job.job_id,
                    )
            else:
                logger.warning(
                    "[%s] GPU pre-flight FAILED (NAMD CUDA tile-list bug on this "
                    "geometry) — paused for user decision (Gate B2).",
                    job.job_id,
                )
                job.decision = build_cpu_reroute_decision(bool(cpu_bin))
                job.status = MdStatus.paused
                job.save(workspace_dir)
                return

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
        logger.error(
            "[%s] Refusing to start %s: only %.1f GB free (floor %.0f GB)",
            job.job_id,
            label,
            fb / GiB,
            ABORT_MIN_FREE_BYTES / GiB,
        )
        job.status = MdStatus.failed
        job.failure_kind = "disk_full"
        job.error = (
            f"Not enough free disk to start {label}: {fb / GiB:.1f} GB free, "
            f"need at least {ABORT_MIN_FREE_BYTES / GiB:.0f} GB. "
            "Free up space (delete old jobs or change their directory), then resume."
        )
        job.save(workspace_dir)
        return False

    # ── Minimization ─────────────────────────────────────────────────────────

    min_coor = output_dir / f"{min_name}.coor"

    def _set_min_status(status: str) -> None:
        """Stamp the timeline's minimisation row and persist it (no-op on old jobs)."""
        if job.minimization is None:
            return
        changed = job.minimization.status != status
        job.minimization.status = status
        if status == "done" and job.minimization.percent != 100.0:
            job.minimization.percent = 100.0
            changed = True
        elif status == "pending" and job.minimization.percent != 0.0:
            job.minimization.percent = 0.0
            changed = True
        if changed:
            job.save(workspace_dir)

    min_log = package_dir / f"{min_name}.log"

    def _update_min_progress() -> None:
        """Persist bounded live progress from the latest complete ENERGY line."""
        row = job.minimization
        if row is None or row.steps <= 0:
            return
        step = last_namd_timestep_fast(min_log)
        if step is None:
            return
        percent = min(99.9, max(0.0, 100.0 * step / row.steps))
        # The disk guard ticks every 15 s. Avoid rewriting job.json when NAMD has
        # not emitted another complete line during that interval.
        if abs(percent - row.percent) >= 0.001:
            row.percent = percent
            job.save(workspace_dir)

    # A minimisation can OUTLIVE its orchestrator (a dev-server --reload, a server
    # restart): the NAMD child keeps going while the runner's task dies.  Adopt the
    # survivor rather than spawning a second NAMD on the same output files, which would
    # corrupt them.  Mirrors _wait_for_segment_process for segments; ``min_name`` is a
    # conf stem, so the same self-verifying conf-name match applies.
    if not min_coor.exists() and _segment_process_running(min_name):
        logger.info(
            "[%s] Minimization %s is already running (orphaned by a restart) — adopting it "
            "and waiting, rather than starting a second NAMD on the same files.",
            job.job_id,
            min_name,
        )
        job.status = MdStatus.running
        _set_min_status("running")
        job.save(workspace_dir)
        # Minimisation has no trajectory health sample yet, but its ENERGY timestep
        # still drives durable timeline progress while an orphan is adopted.
        await _wait_for_segment_process(
            min_name, guard_dir=package_dir, on_tick=_update_min_progress
        )

    if not min_coor.exists():
        if not _disk_floor_ok("minimization"):
            return
        logger.info("[%s] Running minimization: %s", job.job_id, min_name)
        job.status = MdStatus.running
        _set_min_status("running")
        job.save(workspace_dir)

        _free_host_ram_for_namd(job.job_id, "minimization")
        rc, pid = await _run_namd_async(
            namd_bin,
            min_name,
            package_dir,
            min_log,
            job.threads,
            run_devices,
            job.job_id,
            on_spawn=_persist_pid,
            on_tick=_update_min_progress,
        )
        if rc != 0:
            logger.error(
                "[%s] Minimization failed rc=%d; log=%s", job.job_id, rc, min_log
            )
            job.status = MdStatus.failed
            job.failure_kind = _classify_namd_failure(min_log)
            _cause = extract_error_line_from_file(min_log)
            job.error = (
                f"Minimization failed (rc={rc}). {_cause} (see {min_name}.log)"
                if _cause
                else f"Minimization failed (rc={rc}). See {min_name}.log"
            )
            if job.minimization is not None:
                job.minimization.status = "failed"
            job.save(workspace_dir)
            return
        logger.info("[%s] Minimization done", job.job_id)
    else:
        logger.info("[%s] Minimization already done (skipping)", job.job_id)
    # Reached only when output/{min_name}.coor exists — either just written, or left by
    # an earlier attempt this resume is chaining from.  Either way the step is complete.
    _set_min_status("done")

    # ── Settle-stage restraint reference ──────────────────────────────────────
    # The Note-4 settle stage holds the solute with harmonic restraints while the barostat
    # finds the box size the water actually wants.  Its reference PDB ships with the BUILD
    # pose (prep runs before there are any minimised coordinates), but minimisation moves
    # DNA heavy atoms ~1.2 Å RMSD — restraining back to the build pose would pull against
    # the minimiser for the whole stage, at up to ~11 kcal/mol/Å on the atoms whose clashes
    # minimisation just relieved.  Re-point it at the minimised structure now.
    #
    # Idempotent: the coordinates always come from the same ``.coor`` and the B column is
    # preserved, so a resume that repeats this writes the identical file.  Best-effort —
    # the build-pose reference is a usable fallback, so a failure here must not kill a job.
    retarget_settle_restraints(package_dir, min_coor, job.job_id)

    # ── Declash reference rebuild ─────────────────────────────────────────────
    # For declash designs, re-anchor the ENM ladder, heavy-atom restraints and
    # the C1'/WC health reference to the declashed coordinates produced by the
    # minimisation.  Idempotent (skips if already rebuilt), so it is safe across
    # resume.  Two triggers:
    #   • ``declash`` — the soft ss-excluded ladder (geometric-build extra bases).
    #   • ``rebuild_enm_from_min`` — the oxDNA-SEEDED fast path: the minimise ran with
    #     NO base-ring ENM (no_enm) so the seed backmap's duplex clashes could open;
    #     rebuild the ENM from those declashed coords so k0.1 no longer releases stored
    #     clash energy.  Keeps the fast 4 fs ladder (unlike ``declash``, which is soft).
    #
    # MUST run BEFORE the GPU-resident probe below: that probe seeds from the declashed
    # minimise coords, and for the seeded path the on-disk ENM still encodes the clash
    # until we rebuild it — probing the 4 fs conf against a clash-encoding ENM on already
    # declashed coordinates would blow the 20-step probe up and falsely downgrade
    # GPU-resident for the whole run.
    if manifest.get("declash") or manifest.get("rebuild_enm_from_min"):
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

    # ── GPU-resident pre-flight ───────────────────────────────────────────────
    # The "fast" segments (HMR + rigidBonds all + 4 fs + GPUresident) can fail on
    # this host for two unrelated reasons: a pinned host pool too small for the
    # buffers (WSL2 caps it ~1 GB → cudaMallocHost, K6), or a cell containing vacuum
    # (a water-shell carve → "Low global CUDA exclusion count!" at step 0).  Either
    # way NAMD dies at segment START, hours into a job.  Settle it up front on the
    # first fast segment and, if it can't run, rewrite the fast confs.
    #
    # MUST run AFTER minimisation: the probe seeds from ``min_name``'s output, and the
    # ideal-B-DNA build coordinates have clashes that blow the integrator up at step 1
    # BEFORE the GPU-resident checks fire — which is precisely how a GPU-resident-
    # incompatible package got all the way into production once already.
    if not want_cpu and namd_is_cuda_build(namd_bin):
        fast = next(
            (
                s.name
                for s in segments
                if _has_gpu_resident(package_dir / f"{s.name}.conf")
            ),
            None,
        )
        if fast is not None:
            ok = await asyncio.to_thread(
                gpu_resident_probe,
                package_dir,
                fast,
                namd_bin,
                run_devices,
                job.threads,
                min_name,
            )
            if not ok:
                # Default policy "ask": pause and present a Gate-B decision instead of
                # silently halving throughput. Returns False → exit cleanly; the paused
                # job is not auto-resumed (resume_interrupted_jobs only touches running).
                proceed = await asyncio.to_thread(
                    handle_resident_probe_failure,
                    job,
                    package_dir,
                    workspace_dir,
                )
                if not proceed:
                    return

    # ── Segments ──────────────────────────────────────────────────────────────

    job.status = MdStatus.running
    # A resumed job carries an informational "interrupted/resuming" message in
    # `error` from reconcile.  Clear it now that we are actively running again so
    # the UI never shows a stale "stopped — resume to continue" banner on a live job.
    job.error = None
    job.save(workspace_dir)

    start_idx = job.current_segment_idx
    skip_until = 0  # early-stop: chunks below this were skipped as redundant
    for idx, spec in enumerate(segments):
        if idx < start_idx:
            continue  # resume support
        if idx < skip_until:
            continue  # stage plateaued; this chunk was skipped (already marked done)

        # Mark segment running
        logger.info(
            "[%s] Segment %d/%d: %s (%s)",
            job.job_id,
            idx + 1,
            len(segments),
            spec.name,
            spec.stage,
        )
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
            # (e.g. dev-server reload).  Adopt it instead of spawning a duplicate —
            # WITH the disk guard and in-flight health sampling, so an adopted segment
            # is indistinguishable from one we spawned ourselves.  Without them a
            # routine backend edit left the rest of the run unguarded and its Health
            # card spinning on data that was never collected.
            logger.info(
                "[%s] Adopting running NAMD for %s "
                "(disk guard + in-flight health enabled)",
                job.job_id,
                spec.name,
            )
            _note_health_probe(job, workspace_dir, adopted=True)
            rc = await _wait_for_segment_process(
                spec.name,
                guard_dir=package_dir,
                on_tick=_make_inflight_health_tick(
                    job, spec, package_dir, output_dir, workspace_dir
                ),
            )
            if rc == DISK_ABORT_RC:
                _fail_on_disk_abort(job, spec, idx, package_dir, workspace_dir)
                return
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
            _free_host_ram_for_namd(job.job_id, spec.name)
            rc, pid = await _run_namd_async(
                namd_bin,
                conf_name,
                package_dir,
                seg_log,
                job.threads,
                run_devices,
                job.job_id,
                on_spawn=_persist_pid,
                # Sample health WHILE the segment runs, so a one-segment production run
                # shows a trend instead of a single number ~13 hours later.
                on_tick=_make_inflight_health_tick(
                    job, spec, package_dir, output_dir, workspace_dir
                ),
            )

            # Check if we were cancelled while NAMD was running
            if asyncio.current_task().cancelled():
                if pid:
                    _kill_process_group(pid)
                raise asyncio.CancelledError

            if rc == DISK_ABORT_RC:
                _fail_on_disk_abort(job, spec, idx, package_dir, workspace_dir)
                return

            if rc != 0:
                logger.error(
                    "[%s] NAMD failed rc=%d for %s; log=%s",
                    job.job_id,
                    rc,
                    spec.name,
                    seg_log,
                )
                failure_kind = _classify_namd_failure(seg_log)
                # "Periodic cell too small" is not a blow-up — NPT equilibration
                # outgrew the patch grid built at startup. A checkpoint restart
                # rebuilds the grid for the (now smaller) box and continues, so
                # leave the job RUNNING and let the supervisor auto-resume it (up
                # to a per-segment cap), instead of dead-ending on a healthy run.
                seg = job.segments[idx] if idx < len(job.segments) else None
                if failure_kind == FAILURE_CELL_SHRINK and seg is not None:
                    cell = _cell_shrink_diagnosis(output_dir, spec.name)
                    # Record the event PERMANENTLY before deciding what to do with it.
                    # The old code set job.failure_kind = None and left only a transient
                    # `error` string, so a run that crashed four times finished
                    # "completed" with no trace — which is how the 2hb_1xT 200 ns run
                    # came to inherit a cell that had collapsed 38 % (exp47).
                    job.cell_shrink_events.append(
                        {
                            "segment": spec.name,
                            "attempt": seg.auto_resumes + 1,
                            **cell,
                        }
                    )
                    if cell["collapsing"]:
                        # Not equilibration. The box was built with vacuum in it, and
                        # resuming only walks further into a cell too small for the
                        # solute. Fail loudly and point at the cause.
                        if idx < len(job.segments):
                            job.segments[idx].status = "failed"
                        job.status = MdStatus.failed
                        job.failure_kind = FAILURE_CELL_SHRINK
                        job.error = (
                            f"{spec.name}: the periodic cell has collapsed to "
                            f"{cell['volume_fraction'] * 100:.0f}% of its initial volume "
                            f"({cell['cell_start_ang']} -> {cell['cell_end_ang']} A) and "
                            f"outgrew the patch grid. That is not NPT equilibration — the "
                            f"box was solvated with vacuum in it (a water-shell carve, or "
                            f"too few waters). Rebuild with a full water box, or run this "
                            f"stage at constant volume. Auto-resume refused: continuing "
                            f"would produce a cell smaller than the solute."
                        )
                        job.save(workspace_dir)
                        logger.error(
                            "[%s] %s: cell collapsed to %.0f%% of initial volume — "
                            "refusing to auto-resume (box is under-filled)",
                            job.job_id,
                            spec.name,
                            cell["volume_fraction"] * 100,
                        )
                        return
                    if (
                        seg.auto_resumes < MAX_CELL_SHRINK_RESUMES
                        and _resume_step(output_dir, spec.name, spec.steps) is not None
                    ):
                        seg.auto_resumes += 1
                        # Note 4: "Sometimes the bubbles are large enough that their
                        # removal would cause an abrupt change in the box size, resulting
                        # in unstable MD simulations. In this case, increasing
                        # langevinPistonPeriod and langevinPistonDecay by a factor of 10
                        # can be helpful."  A cell that outgrew its patch grid IS that
                        # abrupt change, so soften the barostat before retrying instead of
                        # replaying the same collapse against the same piston.
                        _soften_piston_in_conf(
                            package_dir / f"{spec.name}.conf", job.job_id, spec.name
                        )
                        seg.status = "running"
                        job.status = MdStatus.running
                        job.failure_kind = None
                        job.error = (
                            f"{spec.name}: periodic cell outgrew the patch grid during "
                            f"NPT equilibration (cell at "
                            f"{cell['volume_fraction'] * 100:.0f}% of initial volume); "
                            f"auto-resuming from the last checkpoint "
                            f"(attempt {seg.auto_resumes}/{MAX_CELL_SHRINK_RESUMES})."
                        )
                        job.save(workspace_dir)
                        logger.warning(
                            "[%s] %s hit periodic-cell-too-small at %.0f%% of initial "
                            "volume; auto-resuming from checkpoint (attempt %d/%d)",
                            job.job_id,
                            spec.name,
                            cell["volume_fraction"] * 100,
                            seg.auto_resumes,
                            MAX_CELL_SHRINK_RESUMES,
                        )
                        return
                # A host pinned-memory OOM is usually a transient starvation, not a
                # size limit (the same allocation succeeded on the previous segment).
                # Leave the job RUNNING so the supervisor relaunches it after a short
                # delay — from the mid-segment checkpoint if one exists, else fresh
                # from the previous segment's coordinates. Bounded so a genuinely
                # under-RAM machine still fails (with the host-OOM Fix popup).
                if (
                    failure_kind == FAILURE_HOST_OOM
                    and seg is not None
                    and seg.auto_resumes < MAX_HOST_OOM_RESUMES
                ):
                    seg.auto_resumes += 1
                    seg.status = "running"
                    job.status = MdStatus.running
                    job.failure_kind = None
                    job.error = (
                        f"{spec.name}: host (CPU) memory was momentarily exhausted "
                        f"while pinning GPU staging buffers; auto-resuming "
                        f"(attempt {seg.auto_resumes}/{MAX_HOST_OOM_RESUMES})."
                    )
                    job.save(workspace_dir)
                    logger.warning(
                        "[%s] %s hit host pinned-memory OOM; auto-resuming "
                        "(attempt %d/%d)",
                        job.job_id,
                        spec.name,
                        seg.auto_resumes,
                        MAX_HOST_OOM_RESUMES,
                    )
                    return
                # A RATTLE / "atoms moving too fast" blow-up is a strained-seed problem,
                # not a transient — the same rigidBonds-all + 4 fs conf from the same
                # coordinates would just re-crash. SOFTEN the failing segment AND every
                # later hard segment to the 1 fs soft integrator (the config the ladder's
                # gentle first chunk already uses), clear the crashed segment's partial
                # checkpoint so it restarts FRESH from the last stable stage endpoint, and
                # let the supervisor relaunch. This is the AUTOMATIC form of the manual
                # force_soft "Fix". Bounded, and a conf already soft is NOT re-softened
                # (rewritten==[]), so a genuinely un-relaxable seed dead-ends instead of
                # looping.
                if (
                    failure_kind == FAILURE_INSTABILITY
                    and seg is not None
                    and seg.auto_resumes < MAX_INSTABILITY_RESUMES
                ):
                    rewritten = soften_stability_confs(
                        package_dir, job.segments, idx, job.job_id
                    )
                    if rewritten:
                        _clear_segment_restart_files(output_dir, spec.name)
                        seg.auto_resumes += 1
                        seg.status = "running"
                        job.status = MdStatus.running
                        job.failure_kind = None
                        job.error = (
                            f"{spec.name}: RATTLE/instability on a strained seed — "
                            f"auto-softened the remaining ladder to the 1 fs soft "
                            f"integrator and resuming from the last stable checkpoint "
                            f"(attempt {seg.auto_resumes}/{MAX_INSTABILITY_RESUMES})."
                        )
                        job.save(workspace_dir)
                        logger.warning(
                            "[%s] %s hit a RATTLE/instability; auto-softened %d "
                            "segment(s) and resuming (attempt %d/%d)",
                            job.job_id,
                            spec.name,
                            len(rewritten),
                            seg.auto_resumes,
                            MAX_INSTABILITY_RESUMES,
                        )
                        return
                if seg is not None:
                    seg.status = "failed"
                job.status = MdStatus.failed
                job.failure_kind = failure_kind
                _cause = extract_error_line_from_file(seg_log)
                job.error = (
                    f"NAMD failed for {spec.name} (rc={rc}). {_cause} (see {seg_log.name})"
                    if _cause
                    else f"NAMD failed for {spec.name} (rc={rc}). See {seg_log.name}"
                )
                job.save(workspace_dir)
                return

        # Append performance metrics
        _append_metrics_jsonl(output_dir, spec.name, spec.stage, seg_log)

        # Health check after every segment (10%, 50%, 100% of each stage)
        run_check = spec.percent >= 10.0
        if run_check:
            logger.info("[%s] Health check: %s", job.job_id, spec.name)
            hresult = (
                HealthCheckResult(
                    passed=True,
                    blocking=False,
                    reason="DNA structural metrics are not applicable to a graphene-only control.",
                )
                if graphene_only
                else run_health_check(
                    package_dir,
                    spec.name,
                    job.name_stem,
                    min_c1_paired=spec.min_c1_paired,
                    min_wc_ref_relative=spec.min_wc_ref_relative,
                )
            )
            logger.info(
                "[%s] Health: c1=%.3f wc=%.3f passed=%s%s",
                job.job_id,
                hresult.c1_paired_fraction or 0.0,
                hresult.wc_ref_relative_fraction or 0.0,
                hresult.passed,
                ("" if hresult.passed else f" WARN: {hresult.reason or hresult.error}"),
            )
            append_health_jsonl(output_dir, spec.name, spec.stage, hresult)

            # ── the Aksimentiev box-trace criterion ──────────────────────────
            # "The box should shrink in the first 300 ps.  After that the box size
            # should become stable."  Reported for every barostatted stage: a cell that
            # never flattens means the box does not hold the right amount of water, and
            # that used to be invisible until a 200 ns run finished in a collapsed cell.
            if getattr(spec, "npt", False):
                _record_settle_report(job, spec, output_dir, workspace_dir)

            # ── the Aksimentiev RMSD criterion (their Fig. 7) ────────────────
            # Deviation from the idealised design, which plateaus when the structure
            # has finished relaxing.  Local-only by construction — it needs the Design.
            _record_design_rmsd(job, spec, output_dir, workspace_dir)

            # Save health sample to job object
            sample = MdHealthSample.from_result(
                hresult, spec.stage, spec.name, blocking=hresult.blocking
            )
            job.health_samples.append(sample)

            # Health is advisory only — a below-threshold checkpoint (C1' or WC,
            # or a diagnostic compute error) is recorded on the sample and flagged
            # in the UI as a warning, but it never stops the run.
            if not hresult.passed:
                logger.warning(
                    "[%s] Health warning after %s (below threshold, continuing): %s",
                    job.job_id,
                    spec.name,
                    hresult.reason or hresult.error,
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
                if graphene_only:
                    decision = energy_plateaued(frames)
                    diag = {
                        "n_energy_frames": len(frames),
                        "energy_plateaued": decision,
                        "dna_metrics": "not_applicable",
                    }
                else:
                    decision, diag = should_early_stop_stage(frames, hresult.wc_per_frame)
                if decision:
                    # Every remaining graphene rung differs only in DNA restraint
                    # files that are empty for this control, so one stable energy
                    # plateau completes relaxation rather than entering three more
                    # physically identical stages.
                    if graphene_only:
                        last_idx = len(segments) - 1
                    skipped_names = []
                    for j in range(idx + 1, last_idx + 1):
                        if j < len(job.segments):
                            job.segments[j].status = "done"
                            job.segments[j].skipped = True
                        skipped_names.append(segments[j].name)
                    # Skipped chunks never ran, so their restart files are absent —
                    # bridge the chain so the next stage restarts from this chunk.
                    _alias_skipped_stage_outputs(output_dir, spec.name, skipped_names)
                    skip_until = last_idx + 1
                    job.current_segment_idx = skip_until
                    job.save(workspace_dir)
                    logger.info(
                        "[%s] early-stop: stage '%s' plateaued at %s (%s) — skipped %d chunk(s)",
                        job.job_id,
                        spec.stage,
                        spec.name,
                        diag,
                        last_idx - idx,
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
    # Minimization has no periodic restart coordinates. A resume deliberately reruns
    # it from the beginning, so show it as pending rather than leaving a stopped job
    # with a spinning minimization row or a misleading partial percentage.
    if job.minimization is not None and job.minimization.status == "running":
        job.minimization.status = "pending"
        job.minimization.percent = 0.0


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

    # Persist synchronously for BOTH spawned and adopted runs. Deferring this to the
    # runner thread left a race with the periodic interrupted-job supervisor: it could
    # observe no handle + status=running and relaunch minimization before the thread's
    # finally block recorded the user's stop.
    if job is not None:
        try:
            job = MdJob.load(job_id, workspace_dir)
        except Exception:  # noqa: BLE001 — retain the already-loaded record
            pass
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
