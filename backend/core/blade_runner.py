"""
BLADE Runner — background execution of a single BLADE implicit-solvent relax.

BLADE = box-free CHARMM36 + OBC2 atomistic propagator (see :mod:`backend.core.blade_job`).

Unlike CanDo/SNUPI — pure in-process scipy solves — a BLADE job's compute is **OpenMM**, and
``openmm``/``parmed`` are installed ONLY in the micromamba ``gpu`` environment.  So a run is
two process hops:

    server (uv env)
      └─ detached worker  ``python -m backend.core.blade_worker <ws> <job_id>``   [uv env]
           ├─ build the CHARMM topology (psfgen) → ideal.pdb + solute.psf
           └─ ``<gpu-env python> -m backend.ml.propagator.blade_relax_gpu cfg.json``  [gpu env]

The worker is launched with ``start_new_session=True`` (its own session/process group) for the
same operational reason SNUPI's is: the dev server runs under ``uvicorn --reload``, and an
in-process thread dies whenever anything under ``backend/`` is saved mid-run.  A detached child
is not reached by the reloader's group signal; it finishes and writes its result, which the
restarted server picks up via :func:`reconcile_blade_status`.

Relaxed coordinates are Physical-layer / display state only — never written back into Design
topology (CLAUDE.md Three-Layer Law).
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
from backend.core.blade_job import BladeJob, BladeStatus

logger = logging.getLogger(__name__)

# Repo root — the cwd the detached worker is launched from, so ``python -m
# backend.core.blade_worker`` resolves the ``backend`` package.  This file is
# backend/core/blade_runner.py, so parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Candidate micromamba/conda prefixes holding an env with openmm + parmed.  ``$BLADE_OPENMM_ENV``
# (an env PREFIX, not the interpreter) overrides everything — set it when the env lives elsewhere.
_ENV_CANDIDATES = (
    "~/micromamba/envs/gpu",
    "~/mambaforge/envs/gpu",
    "~/miniforge3/envs/gpu",
    "~/miniconda3/envs/gpu",
    "~/anaconda3/envs/gpu",
)


def find_blade_python() -> Optional[str]:
    """Path to the interpreter that can ``import openmm`` — or None if we can't find one.

    Mirrors the ``find_oxdna()`` / ``find_namd()`` convention (resolver lives with the runner;
    ``engines.py`` imports it for the status panel).  Order: ``$BLADE_OPENMM_ENV`` prefix, then
    the usual micromamba/conda ``gpu`` env locations.  We only check that the interpreter
    EXISTS here — actually importing openmm costs seconds, so the deep probe is
    :func:`blade_available`, which the availability endpoint caches.
    """
    override = os.environ.get("BLADE_OPENMM_ENV")
    candidates = [override] if override else list(_ENV_CANDIDATES)
    for prefix in candidates:
        if not prefix:
            continue
        py = Path(prefix).expanduser() / "bin" / "python"
        if py.exists():
            return str(py)
    return None


def blade_available() -> tuple[bool, str]:
    """(usable, reason) — the deep probe behind ``GET /blade/available``.

    Checks the three things a run actually needs: the gpu-env interpreter, ``openmm`` +
    ``parmed`` importable inside it, and ``psfgen`` on hand for the topology build.  Returns a
    human reason on failure so the tab can render a specific ⚠ badge instead of a bare
    "unavailable".
    """
    py = find_blade_python()
    if not py:
        return False, (
            "No OpenMM environment found. Expected a micromamba/conda env with "
            "openmm+parmed (e.g. ~/micromamba/envs/gpu), or set $BLADE_OPENMM_ENV "
            "to its prefix."
        )
    try:
        proc = subprocess.run(
            [py, "-c", "import openmm, parmed; print(openmm.version.version)"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not run the OpenMM interpreter ({py}): {exc}"
    if proc.returncode != 0:
        return False, f"{py} cannot import openmm/parmed: {proc.stderr.strip()[:300]}"
    from backend.core.namd_topology import find_psfgen

    try:
        psfgen = find_psfgen()
    except Exception:  # noqa: BLE001
        psfgen = None
    if not psfgen:
        return False, (
            "psfgen not found — BLADE builds its CHARMM topology with it. "
            "Set $NADOC_PSFGEN_BIN or install NAMD."
        )
    return True, f"OpenMM {proc.stdout.strip()} via {py}"


# ── Detached-worker registry ──────────────────────────────────────────────────
# Liveness is the worker PID persisted on the job (``job.pid``), which survives a server
# reload; this in-process map is only a fast path + a zombie reaper for children started HERE.

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
    """True while the detached worker for ``job_id`` is alive.

    Authoritative source is the job's persisted status + pid (survives a server reload);
    without a workspace the in-process ``_STARTED`` map is the fallback.
    """
    if workspace_dir is not None:
        try:
            job = BladeJob.load(job_id, workspace_dir)
        except Exception:  # noqa: BLE001
            job = None
        if job is not None:
            if job.status != BladeStatus.running:
                return False
            return _pid_alive(job.pid)
    return _pid_alive(_STARTED.get(job_id))


def _kill_pid(pid: int) -> None:
    """SIGTERM→SIGKILL the worker.  A ``start_new_session`` child is its own group leader
    (pgid == pid), so we group-kill it — which matters here in a way it doesn't for SNUPI:
    the OpenMM child is a GRANDchild of the server, and killing only the worker would leave
    it holding the GPU.  Group-kill reaps the whole tree."""
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


def prepare_blade_job(design: Design, job: BladeJob, workspace_dir: Path) -> None:
    """Write a self-contained ``design.json`` snapshot into the job dir, so the run
    (and every display read) is decoupled from live editor state."""
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
    """Load a cached JSON payload from the job dir, or None."""
    p = job_dir / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return None


def load_display(job_dir: Path) -> Optional[dict]:
    """The cached relaxed-structure display payload, or None."""
    return load_cached(job_dir, "display.json")


def load_trajectory(job_dir: Path) -> Optional[dict]:
    """The cached relaxation trajectory ({keys, frames, n_frames}) for playback, or None."""
    return load_cached(job_dir, "trajectory.json")


def load_result(job_dir: Path) -> Optional[dict]:
    """The gpu-env script's summary (rmsd/rg/platform/wall), or None."""
    return load_cached(job_dir, "result.json")


# ── NAMD seed handoff (seed_namd — Phase 2) ────────────────────────────────────
# A completed relax gives an EXACT all-atom conformation in psfgen atom order — the
# ideal seed for a solvated NAMD run.  Unlike oxDNA/mrDNA (which reconstruct an atomistic
# model from a coarse-grained frame, re-guessing detail), BLADE's ``relaxed.pdb`` IS the
# atomistic structure, so the handoff is a coordinate read, not a reconstruction: we hand
# NAMD's solvation the raw (N,3) coords via ``build_namd_solvated_package(solute_coords=)``.
# Output is a NAMD INPUT artifact — Physical-layer only, never written back into topology.


class BladeNamdSeed:
    """A BLADE-relaxed structure ready to seed a NAMD run.

    ``solute_coords`` is an (N_atoms, 3) float array in Å, in the SAME psfgen atom order
    ``build_charmm_psfgen_topology(design)`` emits — which the solvation step rebuilds from
    ``design``, so the order matches by construction (both derive from the same builder on
    the same snapshot).  ``design`` is the BLADE job's OWN snapshot, NOT the live editor
    design (they can differ, and a mismatch would scramble the atom-order contract).
    """

    __slots__ = ("design", "solute_coords", "n_atoms", "source_job_id")

    def __init__(self, design, solute_coords, source_job_id):
        self.design = design
        self.solute_coords = solute_coords
        self.n_atoms = len(solute_coords)
        self.source_job_id = source_job_id


def _parse_pdb_xyz(pdb_text: str):
    """Parse ATOM/HETATM x/y/z (Å) out of a PDB into an (N,3) float array.

    Fixed-width columns 31-54 (0-based 30:38 / 38:46 / 46:54), the same convention the
    NAMD solvate step's ``_overwrite_solute_coords`` reads — so the row order this yields
    from ``relaxed.pdb`` matches the order that code overwrites.
    """
    import numpy as np

    rows = []
    for ln in pdb_text.splitlines():
        if ln.startswith(("ATOM", "HETATM")):
            rows.append((float(ln[30:38]), float(ln[38:46]), float(ln[46:54])))
    return np.asarray(rows, dtype=float)


def assert_blade_namd_seed_available(job_id: str, workspace_dir: Path) -> None:
    """Cheap precheck that a NAMD seed CAN be built from this BLADE job — WITHOUT parsing
    the (large) relaxed PDB.  Lets the create-job route reject a bad ``blade_job_id`` with a
    fast 400 before any work is queued.  Raises FileNotFoundError with a user-facing message.
    """
    job = BladeJob.load(job_id, workspace_dir)  # FileNotFoundError if unknown
    jd = job.job_dir(workspace_dir)
    if job.status != BladeStatus.completed:
        raise FileNotFoundError(
            f"BLADE job {job_id} is {job.status.value}, not completed — run a relax first "
            f"before seeding NAMD from it."
        )
    if not (jd / "relaxed.pdb").exists():
        raise FileNotFoundError(
            f"BLADE job {job_id} has no relaxed.pdb; cannot build a NAMD seed."
        )
    if not (jd / "design.json").exists():
        raise FileNotFoundError(
            f"BLADE job {job_id} has no design.json snapshot; cannot build a NAMD seed."
        )


def build_namd_seed_from_blade(job_id: str, workspace_dir: Path) -> BladeNamdSeed:
    """Build a NAMD starting-structure seed from a completed BLADE relax.

    Reads the job's OWN ``design.json`` snapshot (never the live editor design — they can
    differ, and only the snapshot guarantees the psfgen atom order matches the relaxed
    coords) and the exact all-atom ``relaxed.pdb``.  Raises FileNotFoundError if either is
    missing or the job hasn't completed.
    """
    job = BladeJob.load(job_id, workspace_dir)
    jd = job.job_dir(workspace_dir)
    if job.status != BladeStatus.completed:
        raise FileNotFoundError(
            f"BLADE job {job_id} is {job.status.value}, not completed."
        )
    design = _load_snapshot_design(jd)
    if design is None:
        raise FileNotFoundError(
            f"BLADE job {job_id} has no design.json snapshot; cannot build a NAMD seed."
        )
    pdb = jd / "relaxed.pdb"
    if not pdb.exists():
        raise FileNotFoundError(
            f"BLADE job {job_id} has no relaxed.pdb; run a relax first."
        )
    coords = _parse_pdb_xyz(pdb.read_text())
    if not len(coords):
        raise FileNotFoundError(f"BLADE job {job_id} relaxed.pdb has no ATOM records.")
    return BladeNamdSeed(design=design, solute_coords=coords, source_job_id=job_id)


# ── Progress ──────────────────────────────────────────────────────────────────


def _estimate_seconds(job: BladeJob) -> float:
    """Fallback wall-clock estimate, used only until the gpu script reports its first real
    progress line.  Calibrated on the curved-6hb relax measured this cycle: ~2 600 atoms,
    400 minimize iters + 3 ps Langevin ≈ 72 s end-to-end on CUDA.  Cost is ~linear in atom
    count (the 18 Å cutoff keeps GBSA ~O(N)) and ~linear in the Langevin time.

    CPU has no cutoff-driven O(N) win in practice and measures ~20× slower — a bad estimate
    there just means the bar crawls to its cap, which is honest for a run that IS slow.
    """
    atoms = max(1.0, job.n_nucleotides * 20.0)  # ≈ 20 heavy+H atoms per nucleotide
    scale = atoms / 2600.0
    est = 8.0 + scale * (
        (job.minimize_iters / 400.0) * 20.0 + (job.langevin_ps / 3.0) * 45.0
    )
    if (job.platform or "CUDA").upper() == "CPU":
        est *= 20.0
    return max(5.0, est)


PROGRESS_FILE = "progress.json"


def write_progress(
    job_dir: Path, fraction: float, phase: str, info: dict | None = None
) -> None:
    """Publish REAL progress from the (detached) worker to the job dir.

    Written atomically — the server polls this file while the worker runs, and a torn read
    would show a nonsense percentage.  Best-effort: a progress-write failure must never kill a
    run that has already burned minutes of GPU."""
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
    """Append a timestamped line to the job's ``worker.log`` — the thing you ``tail -f`` when a
    relax has been running a while and you want to know it is still moving."""
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


def job_progress(job: BladeJob, workspace_dir: Path) -> dict:
    """Overall progress fraction + ETA for the panel.

    BLADE publishes REAL progress: the gpu script streams a fraction (minimize occupies the
    first 25 %, the Langevin leg the rest), so the ETA comes from the observed rate rather than
    a wall-clock guess.  :func:`_estimate_seconds` covers only the gap before the first report —
    which on a big system is the topology build, and can be a minute of psfgen.
    """
    stage = job.stages[0] if job.stages else None
    overall = 0.0
    eta_seconds: float | None = None
    phase: str | None = None
    detail: dict = {}
    if job.status == BladeStatus.completed:
        overall = 1.0
    elif job.status in (BladeStatus.failed, BladeStatus.stopped):
        overall = 0.0
    elif job.status == BladeStatus.running and stage and stage.started_at:
        elapsed = time.time() - stage.started_at
        prog = read_progress(job.job_dir(workspace_dir))
        frac = (prog or {}).get("fraction")
        if frac is not None and frac > 0.0:
            phase = prog.get("phase")
            overall = min(0.99, float(frac))
            eta_seconds = max(0.0, elapsed / max(frac, 1e-3) - elapsed)
            detail = {
                k: prog.get(k)
                for k in ("step", "n_steps", "steps_per_s", "n_atoms", "platform_used")
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
        **detail,
    }


# ── Execution ─────────────────────────────────────────────────────────────────


def build_solute_inputs(design: Design, jd: Path) -> dict:
    """Build the OpenMM inputs for ``design`` in the job dir → the gpu-script config dict.

    Writes ``ideal.pdb`` (idealized B-DNA all-atom coordinates) and ``solute.psf`` (the CHARMM
    topology), and points at the repo force field.  This is the uv-env half — it needs psfgen
    but NOT openmm.

    ``build_charmm_psfgen_topology(design)`` with no ``atomistic_model`` is precisely what
    yields ideal B-DNA coords; that is the intended BLADE starting point (the whole claim is
    that the relax carries ideal geometry to something physical without explicit water).
    """
    from backend.core.namd_topology import build_charmm_psfgen_topology
    from backend.core.namd_solvate import _FF_DIR, _check_ff_files

    _check_ff_files()
    tb = build_charmm_psfgen_topology(design)
    ideal_pdb = jd / "ideal.pdb"
    solute_psf = jd / "solute.psf"
    ideal_pdb.write_text(tb.pdb_text)
    solute_psf.write_text(tb.psf_text)
    # Atom count straight off the coordinate file — CharmmTopologyBuild.metadata carries no
    # count, and this is the number the gpu script slices the PSF with.
    n_atoms = sum(
        1 for ln in tb.pdb_text.splitlines() if ln.startswith(("ATOM", "HETATM"))
    )
    return {
        "solute_pdb": str(ideal_pdb),
        "psf_path": str(solute_psf),
        "ff_dir": str(_FF_DIR),
        "n_solute": n_atoms,
    }


def relax_and_cache(job: BladeJob, workspace_dir: Path) -> None:
    """Build the topology, run the OpenMM relax in the gpu env, and cache the result.

    This is the body the detached worker process executes (see :mod:`backend.core.blade_worker`)
    and is directly callable in-process for tests/debugging.  It writes the job's TERMINAL
    status (``completed`` / ``failed``) itself and never raises — the worker's only job is to
    call this.  Output is Physical-layer only; never written back into topology.
    """
    jd = job.job_dir(workspace_dir)
    t0 = time.monotonic()
    try:
        design = _load_snapshot_design(jd)
        if design is None:
            raise RuntimeError("job design snapshot (design.json) missing")

        # ── Stage 1: build the solute topology (uv env, psfgen) ──────────────
        if job.stages:
            job.stages[0].status = "running"
            job.stages[0].started_at = time.time()
            job.save(workspace_dir)
        log_worker(jd, "building CHARMM topology (psfgen)…")
        write_progress(jd, 0.01, "build")
        cfg = build_solute_inputs(design, jd)
        job.n_atoms = cfg["n_solute"]
        log_worker(jd, f"topology built: {cfg['n_solute']} atoms")
        if job.stages:
            job.stages[0].status = "done"

        # ── Stage 2: the OpenMM relax (gpu env, detached grandchild) ─────────
        py = find_blade_python()
        if not py:
            raise RuntimeError(
                "No OpenMM environment found (openmm/parmed are not in the backend env). "
                "Set $BLADE_OPENMM_ENV to a micromamba/conda prefix that has them."
            )
        cfg.update(
            {
                "out_pdb": str(jd / "relaxed.pdb"),
                "traj_dcd": str(jd / "relax.dcd"),
                "result_json": str(jd / "result.json"),
                "minimize_iters": job.minimize_iters,
                "langevin_ps": job.langevin_ps,
                "nb_cutoff_A": job.nb_cutoff_A,
                "temp_K": job.temp_K,
                "traj_frames": job.traj_frames,
                "platform": job.platform,
            }
        )
        (jd / "relax_config.json").write_text(json.dumps(cfg, indent=2))
        if len(job.stages) > 1:
            job.stages[1].status = "running"
            job.stages[1].started_at = time.time()
        job.save(workspace_dir)

        log_worker(jd, f"launching OpenMM relax via {py}")
        summary = _run_gpu_relax(py, jd)

        # ── Cache + record ──────────────────────────────────────────────────
        _cache_relax_output(job, jd, summary)
        job.sim_seconds = round(time.monotonic() - t0, 2)
        job.platform_used = summary.get("platform_used")
        job.rmsd_moved_A = summary.get("rmsd_moved_A")
        job.rg_before_A = summary.get("rg_before_A")
        job.rg_after_A = summary.get("rg_after_A")
        if summary.get("n_atoms"):
            job.n_atoms = summary["n_atoms"]
        if not summary.get("finite", True):
            raise RuntimeError(
                "relax produced non-finite coordinates (the run blew up)"
            )
        for st in job.stages:
            st.status = "done"
        job.status = BladeStatus.completed
        job.error = None
        job.save(workspace_dir)
        logger.info(
            "blade job %s completed in %.1fs (%s, %s atoms, rmsd %.2f Å)",
            job.job_id,
            job.sim_seconds,
            job.platform_used,
            job.n_atoms,
            job.rmsd_moved_A or 0.0,
        )

    except Exception as exc:  # noqa: BLE001
        logger.error("blade job %s failed: %s", job.job_id, exc, exc_info=True)
        log_worker(jd, f"FAILED: {exc}")
        job.status = BladeStatus.failed
        job.error = str(exc)
        for st in job.stages:
            if st.status != "done":
                st.status = "failed"
        job.save(workspace_dir)


def _run_gpu_relax(py: str, jd: Path) -> dict:
    """Run the gpu-env relax script, translating its JSON-line stream into job progress.

    We read stdout LINE BY LINE rather than waiting for exit, because that stream is the only
    real progress signal we get out of OpenMM — buffering it until the end would leave the
    panel guessing for the whole run.  Raises on a non-zero exit or an ``error`` event.
    """
    proc = subprocess.Popen(
        [
            py,
            "-m",
            "backend.ml.propagator.blade_relax_gpu",
            str(jd / "relax_config.json"),
        ],
        cwd=str(_REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    summary: dict = {}
    error: str | None = None
    last_logged = -1.0
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            # Not our protocol — an OpenMM/CUDA warning. Keep it in the log, don't choke.
            log_worker(jd, line[:400])
            continue
        kind = ev.get("event")
        if kind == "progress":
            frac = float(ev.get("fraction", 0.0))
            write_progress(
                jd,
                frac,
                ev.get("phase", "relax"),
                {k: ev.get(k) for k in ("step", "n_steps") if ev.get(k) is not None},
            )
            # ~every 10 % so a long run writes ~10 lines, not hundreds.
            if frac - last_logged >= 0.1 or frac >= 1.0:
                last_logged = frac
                log_worker(
                    jd,
                    f"{frac * 100:.0f}%  {ev.get('phase', '')}"
                    + (
                        f"  step {ev.get('step')}/{ev.get('n_steps')}"
                        if ev.get("step") is not None
                        else ""
                    ),
                )
        elif kind == "platform":
            log_worker(
                jd,
                f"platform={ev.get('using')} atoms={ev.get('n')} "
                f"cutoff={ev.get('cutoff_A')} Å",
            )
        elif kind == "platform_fallback":
            # The CUDA→CPU fall-back is a ~20× slowdown, not a detail — say so loudly.
            log_worker(
                jd,
                f"WARNING: {ev.get('requested')} unavailable, falling back to CPU "
                f"({ev.get('error', '')[:200]})",
            )
        elif kind == "minimize_retry":
            # The relax hit a non-finite coordinate (a clashed dense bundle) and is retrying with
            # more minimization — a recovery, not yet a failure.
            log_worker(
                jd,
                f"minimization retry {ev.get('attempt')}: escalating to "
                f"minimize_iters={ev.get('minimize_iters')} "
                f"({ev.get('reason', 'non-finite')})",
            )
        elif kind == "result":
            summary = {k: v for k, v in ev.items() if k != "event"}
        elif kind == "error":
            error = ev.get("message", "unknown error")
            log_worker(jd, f"gpu script error: {error}")
    rc = proc.wait()
    if error:
        raise RuntimeError(f"OpenMM relax failed: {error}")
    if rc != 0:
        raise RuntimeError(f"OpenMM relax exited {rc} (see worker.log)")
    if not summary:
        raise RuntimeError("OpenMM relax produced no result summary (see worker.log)")
    return summary


def _cache_relax_output(job: BladeJob, jd: Path, summary: dict) -> None:
    """Write the display + trajectory caches the frontend reads.

    The raw artifacts (``relaxed.pdb``, ``relax.dcd``) stay on disk as the authoritative
    output — the NAMD-seed hook consumes the PDB directly.  What we cache HERE is the
    display-sized payload: full-atom frames would be ~7 M floats for a 40k-atom / 60-frame run,
    which is not something to push through JSON, so the trajectory is decimated to one
    backbone P atom per nucleotide (≈1 in 20 atoms) for playback.
    """
    display = {
        "relaxed_pdb": str(jd / "relaxed.pdb"),
        "n_atoms": summary.get("n_atoms"),
        "summary": summary,
    }
    (jd / "display.json").write_text(json.dumps(display))
    try:
        traj = _build_trajectory(job, jd)
        if traj and traj.get("n_frames"):
            (jd / "trajectory.json").write_text(json.dumps(traj))
            log_worker(
                jd,
                f"trajectory cached: {traj['n_frames']} frames, "
                f"{traj['n_nucleotides']} nucleotides",
            )
    except Exception as exc:  # noqa: BLE001 — a missing trajectory must not fail a good relax
        log_worker(jd, f"trajectory cache skipped: {exc}")


def _build_trajectory(job: BladeJob, jd: Path) -> Optional[dict]:
    """Read ``relax.dcd`` into the canonical NADOC trajectory payload, or None.

    This deliberately reuses NAMD's :func:`backend.core.md_trajectory.md_composite_trajectory`
    rather than inventing a BLADE format.  The problem is identical — an all-atom CHARMM DCD
    plus its PSF has to become per-nucleotide {keys, frames} — and that function already owns
    the load-bearing parts: the P-atom ordering, the 5'-terminal recovery (so single-stranded
    regions don't render as phantom bases), the base normals, and the ≤200-frame downsample.
    Using it also means the frontend scrubber (``framesToUpdates``) works on BLADE runs with no
    new client decoding at all.

    ``coordinate_path`` is ``ideal.pdb`` — the coordinate file the PSF was built alongside, so
    atom order matches — NOT ``relaxed.pdb``; the DCD supplies the moving coordinates.
    """
    dcd = jd / "relax.dcd"
    psf = jd / "solute.psf"
    ideal = jd / "ideal.pdb"
    if not (dcd.exists() and psf.exists() and ideal.exists()):
        return None
    design = _load_snapshot_design(jd)
    if design is None:
        return None
    from backend.core.md_trajectory import md_composite_trajectory

    return md_composite_trajectory(
        str(psf),
        [("relax", "relax", str(dcd))],
        str(ideal),
        design,
    )


def start_job(job: BladeJob, workspace_dir: Path) -> None:
    """Launch the relax in a DETACHED worker subprocess (its own session) so it survives a
    ``uvicorn --reload`` restart.  Idempotent while a live worker exists.

    Gated on the shared sim guard: a BLADE relax wants the GPU, and starting one while a
    production NAMD/oxDNA/mrDNA job owns the card would slow both and distort the very
    equilibration timings BLADE exists to measure.  ``NADOC_IGNORE_SIM_GUARD=1`` overrides.
    """
    if is_running(job.job_id, workspace_dir):
        return
    _check_sim_guard(job)
    jd = job.job_dir(workspace_dir)
    jd.mkdir(parents=True, exist_ok=True)
    log_fh = open(jd / "worker.log", "w")  # noqa: SIM115 — closed by the reaper thread
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "backend.core.blade_worker",
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
    # both gated on status==running — light up while the detached worker runs.
    job.status = BladeStatus.running
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

    threading.Thread(target=_reap, name=f"blade-reap-{job.job_id}", daemon=True).start()


def _check_sim_guard(job: BladeJob) -> None:
    """Refuse to start a CUDA relax while a heavy production sim owns the machine.

    A CPU-platform job is exempt: it doesn't touch the card, and forcing CPU is exactly the
    escape hatch a user reaches for when the GPU is busy.  Fails OPEN — a probe glitch must
    never block a run.
    """
    if os.environ.get("NADOC_IGNORE_SIM_GUARD"):
        return
    if (job.platform or "CUDA").upper() == "CPU":
        return
    try:
        from backend.core.hardware import heavy_sim_running

        running, reason = heavy_sim_running()
    except Exception:  # noqa: BLE001 — fail open
        return
    if running:
        raise RuntimeError(
            f"A heavy simulation is running on this machine — {reason}. A BLADE relax would "
            f"contend with it for the GPU. Wait for it to finish, choose the CPU platform, or "
            f"set NADOC_IGNORE_SIM_GUARD=1."
        )


def stop_job(job_id: str, workspace_dir: Path) -> bool:
    """Stop a running BLADE job.  Group-kills the detached worker (SIGTERM→SIGKILL), which
    also reaps the OpenMM grandchild holding the GPU.  Marks a still-``running`` job
    ``stopped``.  Returns True if a live worker was found."""
    try:
        job = BladeJob.load(job_id, workspace_dir)
    except Exception:  # noqa: BLE001
        return False
    live = _pid_alive(job.pid)
    if live:
        _kill_pid(job.pid)
        _STARTED.pop(job_id, None)
    # Re-load: the worker may have written a terminal status between our load and the kill.
    try:
        job = BladeJob.load(job_id, workspace_dir)
    except Exception:  # noqa: BLE001
        return live
    if job.status == BladeStatus.running:
        job.status = BladeStatus.stopped
        for st in job.stages:
            if st.status != "done":
                st.status = "failed"
        job.save(workspace_dir)
    return live


def reconcile_blade_status(job: BladeJob, workspace_dir: Path) -> BladeJob:
    """Recover an orphaned ``running`` job whose worker died without writing a terminal status
    (SIGKILLed, or the machine rebooted).  A live worker → unchanged.  Dead worker + cached
    ``display.json`` → ``completed``; dead worker + no cache → ``stopped``.  A worker that
    survives a ``uvicorn --reload`` stays alive (pid still valid) → left ``running``."""
    if job.status != BladeStatus.running:
        return job
    if _pid_alive(job.pid):
        return job
    jd = job.job_dir(workspace_dir)
    if (jd / "display.json").exists():
        job.status = BladeStatus.completed
        for st in job.stages:
            st.status = "done"
        job.save(workspace_dir)
        return job
    job.status = BladeStatus.stopped
    for st in job.stages:
        if st.status != "done":
            st.status = "failed"
    job.save(workspace_dir)
    return job
