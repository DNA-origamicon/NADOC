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
import math
import os
import shutil
import signal
import threading
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Optional

from backend.core.disk_guard import (
    ABORT_MIN_FREE_BYTES,
    DISK_ABORT_RC,
    GiB,
    free_bytes,
    wait_proc_with_disk_guard,
)
from backend.core.models import Design
from backend.core.oxdna_health import (
    FENE_RMAX_UNITS,
    OxdnaHealthResult,
    run_oxdna_health_check,
)
from backend.core.oxdna_job import OxdnaHealthSample, OxdnaJob, OxdnaStatus
from backend.core.oxdna_protocol import (
    OxdnaStageSpec,
    escalate_md_relax_spec,
    expected_energy_lines,
    print_conf_interval,
    render_stage_input,
)
from backend.physics.oxdna_surface_strands import capture_bead_count
from backend.physics.oxdna_interface import (
    surface_anchor_forces_text,
    write_surface_deposition_approach_forces,
    write_surface_deposition_settle_forces,
    write_configuration,
    write_mutual_traps,
    write_topology,
)

logger = logging.getLogger(__name__)


# ── Global task registry ──────────────────────────────────────────────────────


@dataclass
class _RunningHandle:
    thread: threading.Thread
    loop: Optional[asyncio.AbstractEventLoop] = None
    task: Optional[asyncio.Task] = None


_RUNNING: dict[str, _RunningHandle] = {}
_ACTIVE_PIDS: dict[str, int] = {}
_STOP_MARKER = ".stop_requested"


def is_running(job_id: str) -> bool:
    handle = _RUNNING.get(job_id)
    return handle is not None and handle.thread.is_alive()


def _external_oxdna_running(job: OxdnaJob, workspace_dir: Path) -> bool:
    """Detect a detached/orphaned oxDNA process the in-memory registry lost.

    A ``uvicorn --reload`` restart (auto-triggered by any backend .py edit) kills
    the worker that spawned oxDNA; the oxDNA subprocess survives, re-parented to
    init, and keeps writing its stage outputs.  Without this check
    ``reconcile_oxdna_status`` would mislabel that still-running job ``stopped``.

    Scans /proc for a process whose command line references this job's directory
    AND is the oxDNA binary.  Mirrors namd_runner._external_process_running.
    """
    return _external_oxdna_pid(job, workspace_dir) is not None


def _external_oxdna_pid(job: OxdnaJob, workspace_dir: Path) -> Optional[int]:
    """PID of a detached/restarted oxDNA process for this job, found by scanning /proc
    for the job dir in an oxDNA command line — or None.  Matching by the job dir (not a
    stored PID) is self-verifying, so the PID is safe to signal; returned so the caller
    can both detect AND stop the orphan after a server restart."""
    needle = str(job.job_dir(workspace_dir).resolve()).encode()
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
        if needle in cmdline and b"oxdna" in cmdline.lower():
            try:
                return int(proc_dir.name)
            except ValueError:
                return None
    return None


# ── oxDNA binary discovery ────────────────────────────────────────────────────

# Conventional build locations, in *preference order within the same backend
# class*.  ``build_cuda/`` (the doc's separate GPU dir) comes before ``build/``
# (which the auto-build configures with ``-DCUDA=ON``); both before the
# system ``Applications`` path.  ``oxDNA`` on PATH is listed but, because it is
# very often a CPU-only conda/package build, it does NOT automatically win — see
# ``find_oxdna``'s CUDA preference below.
_OXDNA_CANDIDATES = [
    "oxDNA",
    os.path.expanduser("~/oxDNA/build_cuda/bin/oxDNA"),
    os.path.expanduser("~/oxDNA/build/bin/oxDNA"),
    os.path.expanduser("~/Applications/oxDNA/build/bin/oxDNA"),
]

# Cache CUDA-capability by (path, mtime) so the per-request find_oxdna() calls
# don't re-run ldd every time.  mtime keying means a rebuild is picked up.
_CUDA_CAP_CACHE: dict[tuple[str, float], bool] = {}


def oxdna_supports_cuda(path: str) -> bool:
    """True iff the oxDNA binary at ``path`` is linked against the CUDA runtime.

    A CUDA-enabled oxDNA links ``libcudart`` (directly or via
    ``liboxdna_common.so``); a CPU-only build does not.  We read this statically
    with ``ldd`` — fast, no GPU needed, and definitive (the CPU-only conda build
    that silently breaks GPU jobs has no ``libcudart`` line).  A binary whose
    ``libcudart`` resolves to "not found" is treated as NOT CUDA-capable (it
    couldn't load anyway).  Returns False on any probe failure.
    """
    if not path:
        return False
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return False
    if key in _CUDA_CAP_CACHE:
        return _CUDA_CAP_CACHE[key]
    result = False
    ldd = shutil.which("ldd")
    if ldd:
        import subprocess

        try:
            out = subprocess.run(
                [ldd, path],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            for line in out.stdout.splitlines():
                if "libcudart" in line and "not found" not in line:
                    result = True
                    break
        except (OSError, subprocess.SubprocessError):
            result = False
    _CUDA_CAP_CACHE[key] = result
    return result


def _usable_path(candidate: str) -> Optional[str]:
    """Resolve a candidate (PATH name or absolute path) to a runnable file."""
    return shutil.which(candidate) or (
        candidate
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK)
        else None
    )


# ── WSL CUDA driver-library fix ───────────────────────────────────────────────
# On WSL the GPU is reachable ONLY through the Windows-driver passthrough libs in
# /usr/lib/wsl/.  Installing a *native* Linux NVIDIA driver package (e.g.
# ``libnvidia-compute-535``, pulled in as a dependency of Ubuntu's
# ``nvidia-cuda-toolkit`` during a LAMMPS setup) drops a
# ``libnvidia-ptxjitcompiler.so.1`` into /lib/x86_64-linux-gnu and registers it in
# the ldconfig cache.  oxDNA (built with a newer CUDA than the driver's ceiling)
# JIT-compiles its embedded PTX at the first kernel launch and grabs that native
# JIT compiler, which is version-mismatched with the actual WSL driver → SIGSEGV
# on the first force step.  The correct, driver-matched JIT compiler lives in the
# active driver's dir under /usr/lib/wsl/drivers/<inf>/ but that dir is not on the
# ldconfig path, so it loses.  Prepending it to LD_LIBRARY_PATH for the oxDNA
# subprocess makes the WSL driver libs win again.  No sudo, no system changes,
# scoped to the child process; a no-op off WSL or when the dir is absent.
_WSL_DRIVER_DIR_CACHE: list[Optional[str]] = []  # single-slot memo (unset when empty)


def _wsl_gpu_driver_dir() -> Optional[str]:
    """Active WSL GPU-driver library dir containing the PTX JIT compiler, or None.

    Picks the newest (by mtime) /usr/lib/wsl/drivers/*/ dir that ships
    ``libnvidia-ptxjitcompiler.so.1`` — the file that must match the running WSL
    driver.  Returns None off WSL / when no such dir exists.
    """
    if _WSL_DRIVER_DIR_CACHE:
        return _WSL_DRIVER_DIR_CACHE[0]
    result: Optional[str] = None
    try:
        import glob

        matches = glob.glob("/usr/lib/wsl/drivers/*/libnvidia-ptxjitcompiler.so.1")
        if matches:
            newest = max(matches, key=lambda p: os.path.getmtime(p))
            result = os.path.dirname(newest)
    except OSError:
        result = None
    _WSL_DRIVER_DIR_CACHE.append(result)
    return result


def oxdna_subprocess_env() -> Optional[dict]:
    """Environment for the oxDNA subprocess, or None to inherit unchanged.

    On WSL, prepend the active GPU-driver dir to LD_LIBRARY_PATH so the
    driver-matched CUDA/PTX-JIT libs load ahead of any shadowing native Linux
    NVIDIA package (see the module note above).  Returns None when no adjustment
    is needed so the caller can keep inheriting os.environ verbatim.
    """
    driver_dir = _wsl_gpu_driver_dir()
    if not driver_dir:
        return None
    env = os.environ.copy()
    existing = env.get("LD_LIBRARY_PATH", "")
    parts = existing.split(os.pathsep) if existing else []
    if driver_dir not in parts:
        env["LD_LIBRARY_PATH"] = (
            os.pathsep.join([driver_dir, *parts]) if parts else driver_dir
        )
    return env


def find_oxdna(*, prefer_cuda: bool = True) -> Optional[str]:
    """Return the best usable oxDNA binary path, or None if not found.

    Resolution:

    1. ``$OXDNA_BIN`` — explicit override always wins (user intent is absolute).
    2. Otherwise, among the conventional candidates (``oxDNA`` on PATH and the
       ``~/oxDNA`` build dirs), prefer a **CUDA-capable** binary when one exists.

    The CUDA preference is the fix for the most common broken state: a CPU-only
    ``oxDNA`` on PATH (conda/apt) shadowing a perfectly good local GPU build, so
    every ``backend = CUDA`` MD stage aborts with "Backend 'CUDA' not supported".
    Preferring the CUDA binary is never wrong — it runs the CPU backend fine too
    — so this also helps no-GPU machines that happen to have a CUDA build.  Pass
    ``prefer_cuda=False`` to get the plain first-usable behaviour.
    """
    override = os.environ.get("OXDNA_BIN", "").strip()
    if override:
        found = _usable_path(override)
        if found:
            return found

    resolved: list[str] = []
    for candidate in _OXDNA_CANDIDATES:
        found = _usable_path(candidate)
        if found and found not in resolved:
            resolved.append(found)
    if not resolved:
        return None
    if prefer_cuda:
        for found in resolved:
            if oxdna_supports_cuda(found):
                return found
    return resolved[0]


_OXDNA_ANM_CANDIDATES = [
    os.path.expanduser("~/anm-oxdna/oxDNA/build_cuda/bin/oxDNA"),  # CUDA (preferred)
    os.path.expanduser("~/anm-oxdna/oxDNA/build/bin/oxDNA"),  # CPU fallback
]


def find_oxdna_anm() -> Optional[str]:
    """Return the ANM-oxDNA (``DNANM`` hybrid) binary path, or None if not found.

    This is the SEPARATE fork (sulcgroup/anm-oxdna) used only when a design has
    proteins — mainline oxDNA has no DNANM support.  Resolution: ``$OXDNA_ANM_BIN``
    → conventional ``~/anm-oxdna/oxDNA/build_cuda/bin/oxDNA`` (CUDA) → ``…/build/``
    (CPU).  Built by ``scripts/build-anm-oxdna.sh``.
    """
    override = os.environ.get("OXDNA_ANM_BIN", "").strip()
    for candidate in ([override] if override else []) + _OXDNA_ANM_CANDIDATES:
        found = shutil.which(candidate) or (
            candidate
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK)
            else None
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
        found = shutil.which(c) or (
            c if os.path.isfile(c) and os.access(c, os.X_OK) else None
        )
        if found:
            return found
    return None


# ── LAMMPS (CG-DNA / oxDNA) discovery ─────────────────────────────────────────
#
# LAMMPS with the CG-DNA package runs the *same* oxDNA/oxDNA2 force field as the
# standalone oxDNA above, but MPI domain-decomposed — the only oxDNA that scales
# to very large assemblies on CPU cores.  It is a SEPARATE binary (``lmp``), and
# only a build that included the CG-DNA package can run the oxDNA styles, so it is
# discovered + capability-probed independently (mirrors find_oxdna /
# oxdna_supports_cuda).  The runner that uses it is a later phase.

_LAMMPS_CANDIDATES = [
    "lmp",  # modern default name
    "lmp_mpi",
    "lmp_serial",
    os.path.expanduser("~/lammps/build/lmp"),  # conventional source build
    os.path.expanduser("~/Applications/lammps/build/lmp"),
]

# Cache CG-DNA capability by (path, mtime) so per-request find_lammps() calls don't
# re-spawn ``lmp -h`` every time.  mtime keying means a rebuild is picked up.
_CGDNA_CAP_CACHE: dict[tuple[str, float], bool] = {}


def find_lammps() -> Optional[str]:
    """Return the best usable LAMMPS binary path, or None if not found.

    Resolution: ``$LAMMPS_BIN`` override (a name on PATH or an absolute path)
    always wins; otherwise the first usable candidate among ``lmp``/``lmp_mpi``/
    ``lmp_serial`` on PATH and the conventional ``~/lammps/build/lmp`` source
    build.  Presence alone does NOT imply the CG-DNA package — check that with
    ``lammps_supports_cgdna(path)`` (the LAMMPS analog of oxDNA's CUDA-capability
    gate).
    """
    override = os.environ.get("LAMMPS_BIN", "").strip()
    for candidate in ([override] if override else []) + _LAMMPS_CANDIDATES:
        found = _usable_path(candidate)
        if found:
            return found
    return None


def lammps_supports_cgdna(path: str) -> bool:
    """True iff the LAMMPS binary at ``path`` was built with the CG-DNA package.

    Only a CG-DNA build carries the oxDNA/oxDNA2 pair + bond styles NADOC needs.
    ``lmp -h`` prints the compiled-in packages and every available style, so we
    read it statically (fast, no input file) and look for the oxDNA styles /
    the CG-DNA package name.  A plain LAMMPS without CG-DNA reports False — the
    same "present but not capable" signal a CPU-only oxDNA gives for CUDA.
    Returns False on any probe failure.
    """
    if not path:
        return False
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return False
    if key in _CGDNA_CAP_CACHE:
        return _CGDNA_CAP_CACHE[key]
    result = False
    import subprocess

    try:
        out = subprocess.run(
            [path, "-h"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        blob = (out.stdout + out.stderr).lower()
        # "oxdna2/fene" etc. appear in the style lists; "cg-dna" in the installed-
        # packages list.  Either is definitive proof the package is compiled in.
        result = ("oxdna" in blob) or ("cg-dna" in blob)
    except (OSError, subprocess.SubprocessError):
        result = False
    _CGDNA_CAP_CACHE[key] = result
    return result


def lammps_available() -> dict:
    """Probe for a usable CG-DNA-capable LAMMPS (mirror oxdna_available)."""
    bin_path = find_lammps()
    return {
        "available": bin_path is not None,
        "lammps_bin": bin_path,
        "cgdna_capable": lammps_supports_cgdna(bin_path) if bin_path else False,
    }


def oxdna_available() -> dict:
    """Probe for a usable oxDNA binary (mirror md/namd-available)."""
    bin_path = find_oxdna()
    return {
        "available": bin_path is not None,
        "oxdna_bin": bin_path,
        "cuda_capable": oxdna_supports_cuda(bin_path) if bin_path else False,
        "recommended_device": os.environ.get("OXDNA_DEVICE", "0"),
    }


# ── Prepare: write the self-contained job dir ─────────────────────────────────


def prepare_oxdna_job(
    design: Design,
    geometry: list[dict],
    job: OxdnaJob,
    workspace_dir: Path,
    specs: list[OxdnaStageSpec],
    *,
    surface: dict | None = None,
    anchors: list[dict] | None = None,
    anchor_stiff: float = 1000.0,
    surface_strands: dict | None = None,
) -> dict:
    """Write topology.top, conf.dat, design.json, and stages_spec.json into job dir.

    ``geometry`` is the per-nucleotide geometry list (from the geometry route /
    ``_geometry_for_design``) used to seed the initial oxDNA configuration.
    ``specs`` is persisted so the job can resume (rebuild input files) after a
    server restart without re-deriving protocol parameters.

    ``surface`` / ``anchors`` (optional) make the structure relax WHILE bound to a
    hard surface and/or with fixed strands: the repulsion plane + anchor traps are
    appended to forces.txt (alongside the mutual traps) and also written to
    equil_forces.txt (the equil stage drops the mutual traps but keeps these).
    Returns the forces info dict (``n_anchored`` etc.) or an empty dict.
    """
    design = design.without_reference_geometry()
    from backend.physics.oxdna_protein import (
        anm_par_text,
        build_protein_blocks,
        has_proteins,
        hybrid_configuration_text,
        hybrid_topology_text,
        protein_bead_count,
        protein_forces_text,
    )

    jd = job.job_dir(workspace_dir)
    jd.mkdir(parents=True, exist_ok=True)

    # ── Hybrid protein+DNA (ANM-oxDNA / DNANM) ──────────────────────────────────
    # Protein beads occupy the LEADING particle indices, so the topology/conf are
    # the hybrid writers' and every DNA particle index (mutual traps especially)
    # is shifted by +N_protein.  An ANM parameter file + the protein tethers
    # (conjugation springs / positional anchors) are written alongside.
    protein = has_proteins(design)
    prot_offset, prot_traps = 0, ""
    if protein:
        atts, blocks = build_protein_blocks(design, geometry)
        prot_offset = protein_bead_count(blocks)
        (jd / "topology.top").write_text(
            hybrid_topology_text(design, blocks), encoding="utf-8"
        )
        (jd / "conf.dat").write_text(
            hybrid_configuration_text(design, geometry, blocks, oxdna_native_seed=True),
            encoding="utf-8",
        )
        (jd / "anm.par").write_text(anm_par_text(blocks), encoding="utf-8")
        prot_traps = protein_forces_text(design, atts, blocks, geometry)
    else:
        write_topology(design, jd / "topology.top")
        write_configuration(design, geometry, jd / "conf.dat", oxdna_native_seed=True)

    # Optional hard surface + anchors held throughout the relax (a structure relaxed
    # on a surface differs from one relaxed free).  Computed from the ORIGAMI-ONLY conf
    # (before capture strands are appended) so the wall plane sits at the origami extent,
    # not below the capture beads (which we then place exactly on that plane).
    sa_text, info = "", {}
    if surface or anchors:
        sa_text, info = surface_anchor_forces_text(
            design,
            jd / "conf.dat",
            wall=surface,
            anchors=anchors,
            anchor_stiff=anchor_stiff,
        )

    # Surface capture strands: sim-only ssDNA strands (complementary to the overhangs)
    # standing as a B-form helix on the hard surface, held throughout the relax by stiff
    # attach-end traps.  Appended AFTER the origami particles so the origami topology/config
    # are byte-for-byte untouched; requires a surface (they attach to its plane).  Not
    # supported on protein hybrids (leading-index bookkeeping).  See
    # backend/physics/oxdna_surface_strands.py.
    cap_text, cap_info = "", {}
    if surface_strands and surface and not protein:
        from backend.physics.oxdna_surface_strands import (
            CaptureSpec,
            append_capture_strands,
        )

        cspec = (
            surface_strands
            if isinstance(surface_strands, CaptureSpec)
            else CaptureSpec.from_payload(surface_strands)
        )
        if cspec:
            cap_info = append_capture_strands(
                jd / "topology.top", jd / "conf.dat", cspec, surface
            )
            cap_text = cap_info.get("trap_text", "")
            info = {
                **info,
                "capture": {
                    "n_strands": cap_info.get("n_strands", 0),
                    "n_beads": cap_info.get("n_beads", 0),
                    "min_dist_to_origami_nm": cap_info.get("min_dist_to_origami_nm"),
                    "box_nm_grown": cap_info.get("box_nm_grown"),
                    "trap_particles": [
                        p for p, _pos in cap_info.get("trap_anchors", [])
                    ],
                },
            }

    # The equil stage drops the DNA mutual traps but keeps surface/anchors/capture-strand
    # traps AND the protein tethers (so nothing drifts during the unbiased settle).
    equil_extra = "\n".join(t for t in (sa_text, cap_text, prot_traps) if t)
    if surface or anchors or protein or cap_text:
        (jd / "equil_forces.txt").write_text(equil_extra, encoding="utf-8")
    # Mutual-trap external forces (hold designed WC pairs during the relax stages —
    # NADOC geometry starts the pairs outside oxDNA's H-bond range, so without this
    # a free MD melts the structure) + the surface/anchor + protein-tether blocks.
    write_mutual_traps(
        design, jd / "forces.txt", extra_text=equil_extra, particle_offset=prot_offset
    )
    # Self-contained design snapshot for health checks (decoupled from live state).
    (jd / "design.json").write_text(design.model_dump_json())
    (jd / "stages_spec.json").write_text(
        json.dumps([asdict(s) for s in specs], indent=2)
    )
    return info


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

    design: Design
    atomistic_model: (
        object  # AtomisticModel (imported lazily to avoid a heavy import here)
    )
    stage_name: str  # oxDNA stage the coords came from (e.g. "3_equil")
    conf_path: Path  # the last_conf.dat used
    source_job_id: str


def _latest_relaxed_conf(
    job: OxdnaJob, workspace_dir: Path
) -> tuple[Optional[Path], Optional[str]]:
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
    jd = job.job_dir(workspace_dir)
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

    # Recenter the seed on the origin.  oxDNA does NOT fix the centre of mass, so a
    # relaxed conf can sit hundreds of nm out (COM diffusion over the run); the
    # reconstruction faithfully reproduces that absolute position.  Absolute position
    # is irrelevant for a boxed MD seed, but the exported PDB's 8-char coordinate
    # fields overflow past ~±1000 Å — the file silently corrupts and the downstream
    # ENM base-ring scan finds no atoms.  Translate every atom by the model centroid.
    if model.atoms:
        import numpy as _np

        coords = _np.asarray([[a.x, a.y, a.z] for a in model.atoms], dtype=float)
        coords -= coords.mean(axis=0)
        for a, (x, y, z) in zip(model.atoms, coords):
            a.x, a.y, a.z = float(x), float(y), float(z)
        # (Geometry sanity — the reconstruction must preserve the CG extent — is
        # enforced inside build_atomistic_model_from_cg_spline, which raises before
        # we get here if the all-atom placer exploded a heavily-deformed seed.)

    return NamdSeed(
        design=design,
        atomistic_model=model,
        stage_name=stage_name,
        conf_path=conf_path,
        source_job_id=job_id,
    )


def assert_namd_seed_available(job_id: str, workspace_dir: Path) -> None:
    """Cheap precheck that a NAMD seed CAN be built from this oxDNA job.

    Verifies the job exists and has both a ``design.json`` snapshot and a relaxed
    ``last_conf.dat`` — WITHOUT the expensive atomistic reconstruction.  Lets the
    create-job route reject a bad ``oxdna_job_id`` with a fast 400 before any work
    is queued, while the real (slow) :func:`build_namd_seed` runs in the
    background.  Raises FileNotFoundError with a user-facing message otherwise.
    """
    job = OxdnaJob.load(job_id, workspace_dir)  # FileNotFoundError if unknown
    if _load_snapshot_design(job.job_dir(workspace_dir)) is None:
        raise FileNotFoundError(
            f"oxDNA job {job_id} has no design.json snapshot; cannot build a NAMD seed."
        )
    conf_path, _ = _latest_relaxed_conf(job, workspace_dir)
    if conf_path is None:
        raise FileNotFoundError(
            f"oxDNA job {job_id} has no relaxed last_conf.dat yet; run a relaxation first."
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


def _stage_energy_lines_fast(stage_dir: Path) -> int:
    """Cheap ESTIMATE of ``energy.dat``'s line count from the file size and a small
    head sample — O(1) stat + a ~4 KB read, vs :func:`_stage_energy_lines` which reads
    the WHOLE file.  oxDNA writes ``energy.dat`` as fixed-width numeric columns, so
    ``size / mean-bytes-per-line`` is accurate to a line or two.  Used ONLY on the hot
    poll path (:func:`job_overall_fraction`, called ~every 1.5 s while a run is live):
    re-reading a growing energy file each poll contends with oxDNA's own writes and was
    what tripped the frontend's slow-request popup during a run.  The exact counter stays
    for the authoritative reconcile / end-of-stage paths."""
    p = stage_dir / "energy.dat"
    try:
        size = p.stat().st_size
    except OSError:
        return 0
    if size <= 0:
        return 0
    try:
        with p.open("rb") as fh:
            sample = fh.read(4096)
    except OSError:
        return 0
    # Mean bytes/line from the complete lines in the head sample (drop the last,
    # possibly-truncated, fragment). Fall back to the exact count for a file whose
    # first line is longer than the sample (shouldn't happen for energy.dat).
    lines = sample.split(b"\n")
    complete = lines[:-1] if len(lines) > 1 else lines
    counted = sum(1 for ln in complete if ln.strip())
    consumed = sum(len(ln) + 1 for ln in complete)  # +1 for each stripped "\n"
    if counted == 0 or consumed == 0:
        return _stage_energy_lines(stage_dir)
    return max(counted, round(size / (consumed / counted)))


def _live_health_snapshot(design, stage_dir: Path, steps_per_s: float | None) -> dict:
    """Health readout for a stage *while it is still running* — computed on demand
    from the partial stage outputs (oxDNA writes ``energy.dat`` ~100×/stage and
    ``trajectory.dat`` ~10×/stage), so the panel's four cards tick live instead of
    freezing at the previous stage's end-of-stage sample.

    Cheap fields (potential energy, steps/s) come from ``energy.dat``; base-pair
    retention + max backbone clash use the latest COMPLETE trajectory frame
    (``read_trajectory_frames_full`` tolerates a half-written final frame).  All
    reads are best-effort — any parse hiccup leaves that field ``None`` (shown as
    "—") rather than breaking the poll.  Advisory only; the end-of-stage
    ``run_oxdna_health_check`` remains the authoritative gate.
    """
    from backend.core.oxdna_health import (
        base_pair_retention,
        max_backbone_stretch,
        parse_energy_dat,
    )
    from backend.physics.oxdna_interface import read_latest_trajectory_frame_full

    out: dict = {
        "bp_retained_fraction": None,
        "potential_energy": None,
        "max_backbone_clash": None,
        "steps_per_s": steps_per_s,
    }
    try:
        samples = parse_energy_dat(stage_dir / "energy.dat")
        if samples:
            out["potential_energy"] = samples[-1][1]
    except Exception:
        pass
    try:
        frame = read_latest_trajectory_frame_full(stage_dir / "trajectory.dat", design)
        if frame:
            out["bp_retained_fraction"] = base_pair_retention(design, frame)[0]
            out["max_backbone_clash"] = max_backbone_stretch(design, frame)[0]
    except Exception:
        pass
    return out


# ETA rate classes: MC is CPU Monte-Carlo (slow, and a "step" is a sweep); MD-family
# stages (md_relax / equil / production) are CUDA-preferred and far faster.  The two are
# NOT inter-convertible — extrapolating one class's steps/s onto the other's step count
# is what produced the ">100 h" ETA shown during the MC stage (slow MC rate × 1e6 MD
# steps).  ETA estimates each remaining stage with a rate for ITS OWN class.
def _rate_class(kind: str) -> str:
    return "mc" if kind == "mc" else "md"


# Rough steps/s used to SEED a class's ETA before a same-class stage has been observed
# (i.e. estimating the MD stages while still in MC).  Replaced by the real observed rate
# the moment a stage of that class runs, so the seed only governs the first stage's view.
def _default_stage_rate(spec: OxdnaStageSpec, backend: str) -> float:
    if _rate_class(spec.kind) == "mc":
        return 5.0  # CPU Monte-Carlo sweeps/s
    return 1000.0 if (backend or "").upper() == "CUDA" else 400.0  # MD steps/s


def job_overall_fraction(
    job: OxdnaJob, workspace_dir: Path, specs: list[OxdnaStageSpec]
) -> float:
    """Lightweight overall progress fraction (0..1) for the unified job list: completed
    stages plus the running stage's live energy-line fraction, WITHOUT the ETA / health
    work :func:`job_progress` does.  Mirrors ``job_progress()['overall']`` so the master
    progress bar reads the same as the per-stage bar — a SINGLE-stage run (e-field /
    surface / production child) advances smoothly instead of sitting at 0 % until done."""
    n = len(job.stages)
    if not n:
        return 0.0
    done = sum(1 for s in job.stages if s.status == "done")
    idx = job.current_stage_idx
    stage_frac = 0.0
    if 0 <= idx < n and idx < len(specs):
        st = job.stages[idx]
        if st.status == "running":
            # Advisory master-bar fraction on the hot poll path — a size-based estimate
            # avoids re-reading the whole growing energy.dat each poll (see helper).
            stage_dir = job.stage_dir(workspace_dir, st.name)
            lines = _stage_energy_lines_fast(stage_dir)
            live = lines / max(1, expected_energy_lines(specs[idx]))
            # …plus whatever earlier attempts banked, which this attempt's energy.dat
            # knows nothing about.
            banked = (st.completed_steps or 0) / max(1, specs[idx].steps)
            stage_frac = min(1.0, banked + live * (1.0 - banked))
        elif st.status in ("failed", "stopped"):
            # A crashed/stopped stage still did real work. Reading it off disk (rather
            # than reporting 0 %) is what tells you a run is worth resuming.
            stage_frac = stage_fraction(
                job.stage_dir(workspace_dir, st.name), specs[idx]
            )
    return (done + stage_frac) / n


def job_progress(
    job: OxdnaJob, workspace_dir: Path, specs: list[OxdnaStageSpec]
) -> dict:
    """Return overall + current-stage progress fractions + an ETA + a live health
    snapshot for the panel."""
    n = len(job.stages)
    done = sum(1 for s in job.stages if s.status == "done")
    idx = job.current_stage_idx
    stage_frac = 0.0
    eta_seconds: float | None = None
    next_frame_eta_seconds: float | None = None
    frame_index: int | None = None
    live_health: dict | None = None
    if 0 <= idx < n and idx < len(specs):
        st = job.stages[idx]
        if st.status == "running":
            stage_dir = job.stage_dir(workspace_dir, st.name)
            lines = _stage_energy_lines(stage_dir)
            # THIS attempt's fraction — the ETA rate must be derived from it alone,
            # since started_at is this attempt's start.
            attempt_frac = min(1.0, lines / max(1, expected_energy_lines(specs[idx])))
            banked = (st.completed_steps or 0) / max(1, specs[idx].steps)
            stage_frac = min(1.0, banked + attempt_frac * (1.0 - banked))

            # ── ETA: sum each remaining stage estimated with ITS OWN rate class ───
            # Mixing the slow MC rate with the (1e6-step) MD stages is the bug that
            # showed ">100 h" during MC — estimate per class (MC vs MD-family) instead.
            steps_done = stage_frac * specs[idx].steps
            attempt_steps = attempt_frac * (
                specs[idx].steps - (st.completed_steps or 0)
            )
            live_rate = None
            if st.started_at and attempt_steps > 0:
                live_rate = attempt_steps / max(1e-6, time.time() - st.started_at)

            # Observed steps/s by rate-class from finished stages' health samples …
            kind_by_name = {s.name: s.kind for s in specs}
            rate_by_class: dict[str, float] = {}
            for h in job.health_samples:
                if h.steps_per_s and h.steps_per_s > 0:
                    cls = _rate_class(kind_by_name.get(h.stage, ""))
                    rate_by_class[cls] = h.steps_per_s
            # … plus the live rate of the stage currently running (covers same-class
            # pending stages, e.g. equil after md_relax).
            if live_rate and live_rate > 0:
                rate_by_class[_rate_class(specs[idx].kind)] = live_rate

            def _seconds(j: int, steps_remaining: float) -> float:
                cls = _rate_class(specs[j].kind)
                r = rate_by_class.get(cls) or _default_stage_rate(specs[j], job.backend)
                return steps_remaining / r if r > 0 else 0.0

            eta_seconds = max(
                0.0,
                _seconds(idx, specs[idx].steps - steps_done)
                + sum(_seconds(j, specs[j].steps) for j in range(idx + 1, len(specs))),
            )

            # ── Time to the next DISPLAY frame (last_conf/trajectory write) ───────
            # The relaxed display follows the run live; a new frame lands every
            # print_conf_interval steps.  Estimate the wait to the next one from the
            # current stage's rate so the panel can count it down.
            interval = print_conf_interval(specs[idx])
            frame_index = int(steps_done // interval)
            steps_to_next = (frame_index + 1) * interval - steps_done
            steps_to_next = min(steps_to_next, specs[idx].steps - steps_done)
            cur_rate = (
                live_rate
                if live_rate and live_rate > 0
                else rate_by_class.get(_rate_class(specs[idx].kind))
                or _default_stage_rate(specs[idx], job.backend)
            )
            if cur_rate and cur_rate > 0:
                next_frame_eta_seconds = max(0.0, steps_to_next / cur_rate)

            # ── Live health snapshot (advisory; cards tick mid-stage) ─────────────
            design = _load_snapshot_design(job.job_dir(workspace_dir))
            if design is not None:
                live_health = _live_health_snapshot(
                    design,
                    stage_dir,
                    live_rate or rate_by_class.get(_rate_class(specs[idx].kind)),
                )
        elif st.status in ("failed", "stopped"):
            # A crashed/stopped stage still banked real simulated time. Report it (read
            # off disk, across every attempt) instead of 0 % — that number is what tells
            # you whether the run is worth resuming rather than restarting.
            stage_frac = stage_fraction(
                job.stage_dir(workspace_dir, st.name), specs[idx]
            )
    overall = (done + stage_frac) / n if n else 0.0
    return {
        "overall": overall,
        "done_stages": done,
        "total_stages": n,
        "current_stage_idx": idx,
        "stage_fraction": stage_frac,
        "eta_seconds": eta_seconds,
        "next_frame_eta_seconds": next_frame_eta_seconds,
        "frame_index": frame_index,
        "live_health": live_health,
    }


# ── Low-level subprocess ──────────────────────────────────────────────────────


async def _run_oxdna_async(
    oxdna_bin: str,
    input_path: Path,
    stage_dir: Path,
    log_path: Path,
    job_id: str,
    on_spawn=None,
) -> tuple[int, Optional[int]]:
    """Run oxDNA on *input_path* with cwd=stage_dir; return (returncode, pid).

    ``on_spawn(pid)`` fires right after the process starts (and ``on_spawn(None)`` on
    exit) so the caller can persist the PID to job.json — surviving a server restart so
    ``stop_job`` can signal an orphaned run."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log_fh:
        proc = await asyncio.create_subprocess_exec(
            oxdna_bin,
            str(input_path),
            cwd=str(stage_dir),
            stdout=log_fh,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
            env=oxdna_subprocess_env(),
        )
        pid = proc.pid
        _ACTIVE_PIDS[job_id] = pid
        if on_spawn:
            try:
                on_spawn(pid)
            except Exception:
                pass  # noqa: E722,S110 — persistence must never break the run
        try:
            rc = await wait_proc_with_disk_guard(
                proc, stage_dir, kill=_kill_process_group
            )
        except asyncio.CancelledError:
            _kill_process_group(pid)
            raise
        finally:
            _ACTIVE_PIDS.pop(job_id, None)
            if on_spawn:
                try:
                    on_spawn(None)
                except Exception:
                    pass  # noqa: E722,S110
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


def _health_sample(
    stage_name: str, kind: str, res: OxdnaHealthResult, steps_per_s: Optional[float]
) -> OxdnaHealthSample:
    return OxdnaHealthSample(
        wall_time=time.time(),
        stage=stage_name,
        bp_retained_fraction=res.bp_retained_fraction,
        potential_energy=res.potential_energy,
        max_backbone_clash=res.max_backbone_stretch,
        max_backbone_fene=res.max_backbone_fene_units,
        steps_per_s=steps_per_s,
        passed=res.passed,
        reason=res.reason or (res.error or ""),
    )


def _starting_conf(
    job: OxdnaJob,
    workspace_dir: Path,
    specs: list[OxdnaStageSpec],
    idx: int,
    start_idx: int,
) -> Path:
    """Resolve the starting configuration for stage ``idx``.

    Normally the design conf (stage 0) or the previous stage's ``last_conf.dat``.
    BUT when RESUMING the stage that was killed mid-run (``idx == start_idx`` and
    that stage already wrote its own non-empty checkpoint ``last_conf.dat``),
    continue from THAT checkpoint so the already-simulated time is kept rather
    than restarting the stage from scratch (the "continue from partial frame"
    resume behaviour).  oxDNA writes ``last_conf.dat`` periodically, so a non-empty
    one means the kill happened after at least one checkpoint flush.
    """
    own_last = (
        job.stage_dir(workspace_dir, specs[idx].name) / "last_conf.dat"
    ).resolve()
    if idx == start_idx and own_last.exists() and own_last.stat().st_size > 0:
        return own_last
    if idx == 0:
        return (job.job_dir(workspace_dir) / "conf.dat").resolve()
    return (
        job.stage_dir(workspace_dir, specs[idx - 1].name) / "last_conf.dat"
    ).resolve()


# ── Crash recovery ────────────────────────────────────────────────────────────
#
# A host crash / power loss kills oxDNA mid-write.  `last_conf.dat` is rewritten in
# place every print_conf_interval, so a crash during that write leaves a TORN
# checkpoint: right size, wrong contents (some particle records from step N, some
# from N-1, or a half-written final line).  oxDNA will happily load it, and the
# physically inconsistent frame then blows up thousands of steps later —
# "Invalid cell -2147483648 for particle NNN (pos: inf -inf inf)".
#
# The trajectory file is append-only, so its frames are individually trustworthy:
# a crash can only truncate the LAST one.  It is therefore the reliable fallback.

_CONF_HEADER_LINES = 3  # t = … / b = … / E = …
_CONF_MIN_COLUMNS = 15  # r[3] b[3] n[3] v[3] L[3]


def _conf_body_is_valid(lines: list[str], n_particles: int) -> bool:
    """True when `lines` (the particle records after the 3 header lines) is a complete,
    finite configuration for `n_particles`.  Rejects the torn-checkpoint case that a
    size check alone lets through."""
    if len(lines) < n_particles:
        return False
    for ln in lines[:n_particles]:
        parts = ln.split()
        if len(parts) < _CONF_MIN_COLUMNS:
            return False
        try:
            if not all(math.isfinite(float(v)) for v in parts[:_CONF_MIN_COLUMNS]):
                return False
        except ValueError:
            return False
    return True


def conf_is_restartable(path: Path, n_particles: int) -> bool:
    """Can oxDNA safely restart from this configuration file?"""
    try:
        if not path.exists() or path.stat().st_size == 0:
            return False
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return False
    if len(lines) < _CONF_HEADER_LINES + n_particles or not lines[0].startswith("t ="):
        return False
    return _conf_body_is_valid(lines[_CONF_HEADER_LINES:], n_particles)


def last_complete_trajectory_frame(
    path: Path, n_particles: int
) -> tuple[str, int] | None:
    """Last COMPLETE frame of an append-only oxDNA trajectory, as ``(text, step)``.

    Reads backwards from the end rather than parsing the whole file — these are
    routinely >1 GB and only the tail is needed.  Returns None if no complete frame
    is present.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size == 0:
        return None
    # A frame is 3 header lines + n_particles records of ~90-130 bytes.  Read a
    # generous two-frame window so a complete frame is present even when the final
    # one is truncated, growing the window if the file turns out to be denser.
    window = min(size, (n_particles + _CONF_HEADER_LINES) * 160 * 2 + 4096)
    try:
        with path.open("rb") as fh:
            while True:
                fh.seek(size - window)
                blob = fh.read(window).decode(errors="replace")
                # Drop a partial leading frame — we only trust headers we found whole.
                starts = [
                    i
                    for i in range(len(blob))
                    if blob.startswith("t =", i) and (i == 0 or blob[i - 1] == "\n")
                ]
                if starts and (len(starts) >= 2 or window >= size):
                    break
                if window >= size:
                    break
                window = min(size, window * 2)
    except OSError:
        return None
    for s in reversed(starts):
        frame = blob[s:]
        lines = frame.splitlines()
        if len(lines) < _CONF_HEADER_LINES + n_particles:
            continue
        if not _conf_body_is_valid(lines[_CONF_HEADER_LINES:], n_particles):
            continue
        try:
            step = int(float(lines[0].split("=", 1)[1]))
        except (ValueError, IndexError):
            continue
        body = "\n".join(lines[: _CONF_HEADER_LINES + n_particles])
        return body + "\n", step
    return None


def _attempt_energy_files(stage_dir: Path) -> list[Path]:
    """Every attempt's energy file for this stage, OLDEST first — the archived
    ``energy.rN.dat`` from interrupted runs plus the current ``energy.dat``."""
    return sorted(stage_dir.glob("energy.r*.dat"), key=lambda p: p.name) + [
        stage_dir / "energy.dat"
    ]


def _attempt_steps(path: Path, every: int) -> int:
    """Steps an attempt simulated, from its energy file. The first row is the starting
    state, not a simulated interval, so it is not counted."""
    if not path.exists():
        return 0
    try:
        lines = sum(
            1 for ln in path.read_text(errors="replace").splitlines() if ln.strip()
        )
    except OSError:
        return 0
    return max(0, lines - 1) * every


def _exploded(stage_dir: Path) -> bool:
    """oxDNA writes ``error_conf.dat`` only when it aborts on a diverged configuration
    ("Invalid cell … pos: inf").  Its presence means the CURRENT attempt's checkpoint is
    from a structure already on its way to blowing up, so resuming from that checkpoint
    just reproduces the blow-up — the previous attempt's tail is the safe restart point."""
    p = stage_dir / "error_conf.dat"
    try:
        return p.exists() and p.stat().st_size > 0
    except OSError:
        return False


def resume_point(
    stage_dir: Path, spec: OxdnaStageSpec, n_particles: int
) -> tuple[Path | None, int, str]:
    """Resolve where to resume this stage from, and how much of its step budget that
    point has already consumed.  Returns ``(conf_path, consumed_steps, note)``.

    The restart configuration and the step count MUST come from the same place — a
    blind sum over attempts would credit work that the chosen restart point does not
    actually contain.

    Preference order:
      1. the current attempt's ``last_conf.dat``, if it validates AND the attempt did
         not end in a divergence (``error_conf.dat``);
      2. the newest COMPLETE frame in the current attempt's trajectory;
      3. the same, walking back through the archived ``trajectory.rN.dat`` attempts.

    A recovered frame is written to ``restart_conf.dat`` — a SEPARATE file, so the
    resumed run's own ``lastconf_file`` cannot overwrite the point it started from
    (that overwrite is what previously made a second crash unrecoverable).
    """
    every = spec.print_energy_every_override or max(1, spec.steps // 100)
    energies = _attempt_energy_files(stage_dir)
    # Cumulative steps banked by every attempt STRICTLY BEFORE index i.
    prior = [0]
    for p in energies:
        prior.append(prior[-1] + _attempt_steps(p, every))
    n_attempts = len(energies)  # last entry is the current attempt
    diverged = _exploded(stage_dir)

    last_conf = stage_dir / "last_conf.dat"
    if not diverged and conf_is_restartable(last_conf, n_particles):
        return (
            last_conf.resolve(),
            prior[n_attempts],
            "last_conf.dat (checkpoint intact)",
        )

    if diverged:
        reason = "the attempt DIVERGED (error_conf.dat present)"
    elif not last_conf.exists():
        reason = "last_conf.dat missing"
    else:
        reason = "last_conf.dat TORN (incomplete/non-finite)"

    # Walk attempts newest-first: current trajectory.dat, then trajectory.rN.dat.
    trajectories = [(stage_dir / "trajectory.dat", n_attempts - 1)]
    archived = sorted(
        stage_dir.glob("trajectory.r*.dat"), key=lambda p: p.name, reverse=True
    )
    for k, traj in enumerate(archived):
        trajectories.append((traj, n_attempts - 2 - k))
    for traj, attempt_idx in trajectories:
        if not traj.exists() or attempt_idx < 0:
            continue
        # A diverged attempt's own tail frames are already blowing up — skip it entirely
        # and fall back to the previous attempt, which ended cleanly.
        if diverged and attempt_idx == n_attempts - 1:
            continue
        found = last_complete_trajectory_frame(traj, n_particles)
        if found is None:
            continue
        text, step = found
        consumed = prior[attempt_idx] + step
        out = stage_dir / "restart_conf.dat"
        try:
            out.write_text(text)
        except OSError:
            return None, 0, f"{reason}; recovered frame could not be written"
        return (
            out.resolve(),
            consumed,
            (
                f"{reason} — restarting from step {step:,} of {traj.name} "
                f"({consumed:,} steps of the stage budget banked)"
            ),
        )
    return None, 0, f"{reason} and no complete trajectory frame to fall back on"


def stage_completed_steps(stage_dir: Path, spec: OxdnaStageSpec) -> int:
    """Steps of this stage's budget a resume would keep — CHEAP estimate for display.

    Energy-file arithmetic only: no trajectory scan and no writes, because this runs on
    the job-list poll path.  An attempt that ended in a divergence is excluded, since
    :func:`resume_point` will discard it — counting it would overstate progress.
    :func:`resume_point` is the authoritative version and agrees with this to within one
    ``print_conf_interval``.
    """
    every = spec.print_energy_every_override or max(1, spec.steps // 100)
    files = _attempt_energy_files(stage_dir)
    if _exploded(stage_dir) and files:
        files = files[:-1]  # the current (diverged) attempt is thrown away
    return sum(_attempt_steps(p, every) for p in files)


def stage_fraction(stage_dir: Path, spec: OxdnaStageSpec) -> float:
    """Fraction of this stage's step budget a resume would keep (0..1)."""
    if spec.steps <= 0:
        return 0.0
    return min(1.0, stage_completed_steps(stage_dir, spec) / spec.steps)


def _archive_partial_outputs(stage_dir: Path) -> list[str]:
    """Move a resumed stage's partial trajectory/energy aside before re-running.

    oxDNA opens ``trajectory_file``/``energy_file`` in TRUNCATE mode, so the
    frames already sampled by the interrupted run would be destroyed the instant
    the resumed run starts.  Rename them to ``<stem>.rN.<suffix>`` (N = next free
    index) so they survive and can still be pooled into the flexibility map /
    composite trajectory.  ``last_conf.dat`` is NOT touched — it is the checkpoint
    the resumed run reads from.  Returns the archived file names."""
    archived: list[str] = []
    for base in ("trajectory.dat", "energy.dat"):
        src = stage_dir / base
        if not src.exists() or src.stat().st_size == 0:
            continue
        stem, _, suffix = base.partition(".")
        n = 1
        while (stage_dir / f"{stem}.r{n}.{suffix}").exists():
            n += 1
        dst = stage_dir / f"{stem}.r{n}.{suffix}"
        src.rename(dst)
        archived.append(dst.name)
    return archived


# ── Escalate-and-retry a stuck relax ──────────────────────────────────────────


def _persist_specs(
    job: OxdnaJob, workspace_dir: Path, specs: list[OxdnaStageSpec]
) -> None:
    """Re-write stages_spec.json so a server restart resumes with the (escalated) specs."""
    (job.job_dir(workspace_dir) / "stages_spec.json").write_text(
        json.dumps([asdict(s) for s in specs], indent=2)
    )


def _reset_stage_outputs(stage_dir: Path) -> None:
    """Delete a stage's run outputs so a re-run starts fresh (not a checkpoint resume).

    Clearing ``last_conf.dat`` in particular makes ``_starting_conf`` fall back to the
    PREVIOUS stage's conf instead of resuming this stage's own (stale, differently-
    parameterised) checkpoint."""
    for name in ("last_conf.dat", "energy.dat", "trajectory.dat", "input.txt"):
        f = stage_dir / name
        try:
            if f.exists():
                f.unlink()
        except OSError:
            pass


def _escalate_relax_and_rewind(
    job: OxdnaJob,
    workspace_dir: Path,
    specs: list[OxdnaStageSpec],
    relax_idx: int,
    base_relax_spec: OxdnaStageSpec,
) -> None:
    """Spend one retry: replace the md_relax spec with an escalated copy, clear the
    relax stage (and every later stage) so they re-run fresh, and rewind the job to
    the relax stage.  ``base_relax_spec`` is the pristine (un-escalated) spec so
    escalation is derived from the original, never compounded."""
    job.relax_retries += 1
    specs[relax_idx] = escalate_md_relax_spec(base_relax_spec, job.relax_retries)
    # Reset the relax stage's status object to the escalated step count + clear it and
    # every downstream stage so nothing stale is mistaken for "done"/resumable.
    for i in range(relax_idx, len(specs)):
        job.stages[i].status = "pending"
        job.stages[i].started_at = None
        job.stages[i].resumed = False
        job.stages[i].steps = specs[i].steps
        _reset_stage_outputs(job.stage_dir(workspace_dir, specs[i].name))
    job.current_stage_idx = relax_idx
    _persist_specs(job, workspace_dir, specs)
    job.save(workspace_dir)
    logger.info(
        "[%s] relax not equil-ready → escalating md_relax (attempt %d/%d): "
        "steps=%d dt=%s cap=%s; rewinding to %s",
        job.job_id,
        job.relax_retries,
        job.max_relax_retries,
        specs[relax_idx].steps,
        specs[relax_idx].dt,
        specs[relax_idx].max_backbone_force,
        specs[relax_idx].name,
    )


# ── Unbiased-MD explosion recovery (production / field / run) ──────────────────

# Kinds that run at the fast production timestep and are eligible for dt-halving
# recovery.  Relax/equil stages instead escalate via _escalate_relax_and_rewind.
_DT_HALVE_KINDS = frozenset({"production", "field", "run"})
# Stages whose final structure should stay ~compact, so a large extent increase means a
# numerical blow-up.  Excludes "field": a field run intentionally DEFLECTS/displaces the
# structure under an applied force, so its extent legitimately grows.
_BLOWUP_EXTENT_KINDS = frozenset({"production", "run"})

# Substrings oxDNA prints when a particle's coordinates blow up (the integrator
# diverged — usually too-large a timestep for a transiently stiff/strained contact,
# amplified by mixed-precision CUDA).  Matched case-insensitively in the stage log.
_EXPLOSION_MARKERS = (
    "_max_n_per_cell",  # cell list overflow from huge coordinates
    "particles with very large coordinates",
    "nan",  # NaN energy/coordinate
)


def _log_indicates_explosion(log_path: Path) -> bool:
    """True when the stage's oxDNA log shows a numerical blow-up (vs. a config-load
    or setup error).  Only the tail matters — the explosion is the last thing printed
    before the non-zero exit."""
    try:
        text = log_path.read_text(errors="replace")
    except OSError:
        return False
    tail = text[-4000:].lower()
    return any(marker in tail for marker in _EXPLOSION_MARKERS)


# A sampling stage's final structure whose overall extent has grown past this multiple
# of its relaxed-seed extent has blown apart — even if oxDNA exited 0 (the expansion
# stayed under the hard _max_n_per_cell abort threshold).  Stable production swells
# modestly or bends (extent <= ~1x); a melt/explosion balloons it several-fold.
_EXPLOSION_EXTENT_FACTOR = 2.0


def _conf_max_extent(conf_path: Path) -> "float | None":
    """Largest per-axis coordinate span (oxDNA units) of a configuration, or None if
    unreadable — a cheap rotation-robust proxy for the structure's overall size."""
    try:
        lines = conf_path.read_text(errors="replace").splitlines()
    except OSError:
        return None
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    seen = False
    for ln in lines[3:]:  # skip the t= / b= / E= header lines
        p = ln.split()
        if len(p) < 3:
            continue
        try:
            xyz = (float(p[0]), float(p[1]), float(p[2]))
        except ValueError:
            continue
        if not all(math.isfinite(v) for v in xyz):
            return float("inf")  # NaN/inf coordinate = definitely blown up
        seen = True
        for i in range(3):
            lo[i] = min(lo[i], xyz[i])
            hi[i] = max(hi[i], xyz[i])
    return max(hi[i] - lo[i] for i in range(3)) if seen else None


def _structure_blew_up(stage_dir: Path, ref_conf: Path) -> bool:
    """True if a COMPLETED sampling stage's final structure has expanded far beyond its
    relaxed-seed extent.  Catches the numerical blow-up that finishes without an oxDNA
    abort (so :func:`_log_indicates_explosion` never sees it) and would otherwise hand a
    blown-apart structure to display / measurement."""
    cur = _conf_max_extent(stage_dir / "last_conf.dat")
    ref = _conf_max_extent(ref_conf)
    if cur is None or ref is None or ref < 1e-6:
        return False
    return cur > _EXPLOSION_EXTENT_FACTOR * ref


def _halve_dt_and_restart(
    job: OxdnaJob,
    workspace_dir: Path,
    specs: list[OxdnaStageSpec],
    idx: int,
) -> None:
    """Spend one production retry: halve this sampling stage's timestep and restart it
    from the clean relaxed seed (NOT the exploded checkpoint).  Resetting the stage's
    outputs makes ``_starting_conf`` fall back to the previous stage's relaxed
    ``last_conf.dat`` (or the job's seeded ``conf.dat`` for a production-only job), so
    the re-run integrates the well-relaxed structure at the stabler, finer timestep."""
    job.production_retries += 1
    specs[idx] = replace(specs[idx], dt=specs[idx].dt / 2.0)
    job.stages[idx].status = "pending"
    job.stages[idx].started_at = None
    job.stages[idx].resumed = False
    # This restarts the stage FROM SCRATCH at the relaxed seed, so nothing is banked.
    # Leaving a resume's completed_steps behind would add phantom progress on top of a
    # run that begins at step 0 (a 53 %-banked value made a 20 %-done rerun read 63 %).
    job.stages[idx].completed_steps = 0
    _reset_stage_outputs(job.stage_dir(workspace_dir, specs[idx].name))
    job.current_stage_idx = idx
    _persist_specs(job, workspace_dir, specs)
    job.save(workspace_dir)
    logger.info(
        "[%s] %s went unstable (coordinate blow-up) → halving dt and "
        "restarting from the relaxed seed (attempt %d/%d): dt=%s",
        job.job_id,
        specs[idx].name,
        job.production_retries,
        job.max_production_retries,
        specs[idx].dt,
    )


# ── Main runner coroutine ─────────────────────────────────────────────────────


async def run_job(
    job: OxdnaJob, workspace_dir: Path, specs: list[OxdnaStageSpec]
) -> None:
    """Async coroutine — runs all stages until completion, failure, or cancel."""
    jd = job.job_dir(workspace_dir)
    logger.info("[%s] oxdna run_job starting; job_dir=%s", job.job_id, jd)

    # Hybrid protein jobs (any DNANM stage → spec.parfile set) need the ANM-oxDNA
    # fork; DNA-only jobs use mainline oxDNA.
    is_hybrid = any(s.parfile for s in specs)
    oxdna_bin = find_oxdna_anm() if is_hybrid else find_oxdna()
    if oxdna_bin is None:
        job.status = OxdnaStatus.failed
        job.error = (
            (
                "ANM-oxDNA (protein) binary not found. Set $OXDNA_ANM_BIN or run "
                "scripts/build-anm-oxdna.sh."
            )
            if is_hybrid
            else "oxDNA binary not found. Set $OXDNA_BIN or install to ~/oxDNA/build/bin/oxDNA."
        )
        job.save(workspace_dir)
        return

    design = _load_snapshot_design(jd)
    if design is None:
        job.status = OxdnaStatus.failed
        job.error = "design.json snapshot missing/unreadable; cannot run health checks."
        job.save(workspace_dir)
        return

    topo = (jd / "topology.top").resolve()

    # Persist the live oxDNA PID to job.json on every spawn, so a server restart can
    # still signal the orphaned process (see stop_job's restart fallback).
    def _persist_pid(p: Optional[int]) -> None:
        job.oxdna_pid = p
        job.save(workspace_dir)

    job.status = OxdnaStatus.running
    job.save(workspace_dir)

    start_idx = job.current_stage_idx
    # The md_relax stage is the escalation target: if it finishes but leaves the
    # structure not equil-ready (a backbone bond past oxDNA's FENE cliff), we re-run
    # IT with stronger parameters rather than letting the (capped, but still) equil
    # settle a strained structure — or, historically, crash an uncapped one.  Keep a
    # pristine copy so escalation is derived from the original, never compounded.
    relax_idx = next((i for i, s in enumerate(specs) if s.kind == "md_relax"), None)
    base_relax_spec = replace(specs[relax_idx]) if relax_idx is not None else None

    idx = start_idx
    while idx < len(specs):
        spec = specs[idx]

        stage_dir = job.stage_dir(workspace_dir, spec.name)
        stage_dir.mkdir(parents=True, exist_ok=True)

        conf = _starting_conf(job, workspace_dir, specs, idx, start_idx)
        is_resume = conf == (stage_dir / "last_conf.dat").resolve()
        if is_resume:
            # A host crash can leave last_conf.dat torn — validate it, and fall back to
            # the newest COMPLETE trajectory frame if it fails. Resuming from a torn
            # checkpoint loads without complaint and then explodes a few million steps
            # later with "Invalid cell … (pos: inf)", which reads as a sim instability.
            recovered, already, note = resume_point(
                stage_dir, spec, job.n_nucleotides or 0
            )
            if recovered is None:
                job.status = OxdnaStatus.failed
                job.error = f"cannot resume {spec.name}: {note}"
                job.save(workspace_dir)
                return
            conf = recovered
            archived = _archive_partial_outputs(stage_dir)
            job.stages[idx].resumed = True
            # Continue the STEP BUDGET too, not just the structure. oxDNA always runs
            # with restart_step_counter, so without this the resumed run redoes the
            # stage's full step count and the work already banked is silently repeated.
            remaining = max(1, spec.steps - already)
            if already > 0:
                # Pin the output cadence to the ORIGINAL stage's, so energy/trajectory
                # intervals stay comparable across attempts (they default to steps//100,
                # which a shortened remaining budget would otherwise change mid-stage
                # and desynchronise the cross-attempt progress accounting).
                spec = replace(
                    spec,
                    steps=remaining,
                    print_energy_every_override=(
                        spec.print_energy_every_override
                        or max(1, specs[idx].steps // 100)
                    ),
                    print_conf_interval_override=(
                        spec.print_conf_interval_override
                        or print_conf_interval(specs[idx])
                    ),
                )
            job.stages[idx].completed_steps = already
            logger.info(
                "[%s] resuming stage %s from %s; %s steps already done, "
                "%s remaining (archived partial outputs: %s)",
                job.job_id,
                spec.name,
                note,
                f"{already:,}",
                f"{remaining:,}",
                ", ".join(archived) or "none",
            )
        else:
            # Not a resume — this stage starts at step 0, so nothing is banked. Clearing
            # is load-bearing, not hygiene: a retry (or a re-run after an escalation) of a
            # stage that HAD been resumed would otherwise keep crediting the old attempt.
            job.stages[idx].completed_steps = 0

        input_path = stage_dir / "input.txt"
        # The settle target is intentionally the configuration actually reached by the
        # approach stage. Materialise it only at the stage boundary; projecting selected
        # beads onto the plane before dynamics would create overstretched backbones.
        contact_forces = jd / (spec.forces_file or "deposition_settle_forces.txt")
        if (spec.forces_meta and spec.forces_meta.get("materialize_contact_traps")
                and not contact_forces.exists()):
            try:
                write_surface_deposition_settle_forces(
                    contact_forces,
                    design,
                    conf,
                    wall=spec.forces_meta["wall"],
                    anchors=spec.forces_meta["anchors"],
                    anchor_stiff=float(spec.forces_meta.get("anchor_stiff", 1.0)),
                    max_contact_gap_nm=float(
                        spec.forces_meta.get("max_contact_gap_nm", 0.75)
                    ),
                )
            except (KeyError, ValueError) as exc:
                job.status = OxdnaStatus.failed
                job.error = f"cannot prepare surface-contact restraints: {exc}"
                job.save(workspace_dir)
                return
        # Relax stages use the default mutual-trap forces.txt; a field stage points
        # spec.forces_file at its own field_forces_N.txt (uniform force + anchors).
        forces = (
            (jd / (spec.forces_file or "forces.txt")).resolve()
            if spec.external_forces
            else None
        )
        # The ANM parameter file (hybrid stages) is resolved to an absolute path in
        # the job dir, like topology/conf/forces (oxDNA runs with cwd=stage_dir).
        parfile = str((jd / spec.parfile).resolve()) if spec.parfile else None
        input_path.write_text(
            render_stage_input(
                spec,
                str(topo),
                str(conf),
                forces_name=str(forces) if forces else None,
                parfile_name=parfile,
            )
        )

        logger.info(
            "[%s] stage %d/%d: %s (%s, %d steps)",
            job.job_id,
            idx + 1,
            len(specs),
            spec.name,
            spec.kind,
            spec.steps,
        )
        job.current_stage_idx = idx
        job.stages[idx].status = "running"
        job.stages[idx].started_at = time.time()
        job.save(workspace_dir)

        _fb = free_bytes(stage_dir)
        if _fb < ABORT_MIN_FREE_BYTES:
            logger.error(
                "[%s] Refusing to start %s: only %.1f GB free (floor %.0f GB)",
                job.job_id,
                spec.name,
                _fb / GiB,
                ABORT_MIN_FREE_BYTES / GiB,
            )
            job.stages[idx].status = "failed"
            job.status = OxdnaStatus.failed
            job.error = (
                f"Not enough free disk to start {spec.name}: {_fb / GiB:.1f} GB free, "
                f"need at least {ABORT_MIN_FREE_BYTES / GiB:.0f} GB. "
                "Free up space (delete/archive old jobs), then resume."
            )
            job.save(workspace_dir)
            return

        t0 = time.time()
        log_path = stage_dir / "oxdna.log"
        rc, pid = await _run_oxdna_async(
            oxdna_bin,
            input_path,
            stage_dir,
            log_path,
            job.job_id,
            on_spawn=_persist_pid,
        )
        elapsed = max(1e-6, time.time() - t0)

        stop_marker = jd / _STOP_MARKER
        if stop_marker.exists():
            stop_marker.unlink(missing_ok=True)
            job.stages[idx].status = "stopped"
            job.status = OxdnaStatus.stopped
            job.oxdna_pid = None
            job.save(workspace_dir)
            return

        if asyncio.current_task().cancelled():
            if pid:
                _kill_process_group(pid)
            raise asyncio.CancelledError

        if rc == DISK_ABORT_RC:
            fb = free_bytes(stage_dir)
            logger.error(
                "[%s] Disk guard aborted %s: %.1f GB free",
                job.job_id,
                spec.name,
                fb / GiB,
            )
            job.stages[idx].status = "failed"
            job.status = OxdnaStatus.failed
            job.error = (
                f"Stopped: free disk fell below {ABORT_MIN_FREE_BYTES / GiB:.0f} GB "
                f"while running {spec.name} ({fb / GiB:.1f} GB free). "
                "Free up space (delete/archive old jobs), then resume."
            )
            job.save(workspace_dir)
            return

        if rc != 0:
            # A stage crashed.  First: an unbiased MD sampling stage (production /
            # field / run) that went numerically unstable late in the run — a single
            # particle's coordinates explode and oxDNA aborts.  The relaxed structure
            # was fine (it ran for a while), so escalating the relax is the wrong
            # lever; instead re-run THIS stage at half the timestep from the clean
            # relaxed seed.  Keeps the fast dt the default, auto-stabilises designs
            # that need it (large / floppy structures), no user intervention.
            if (
                spec.kind in _DT_HALVE_KINDS
                and job.production_retries < job.max_production_retries
                and _log_indicates_explosion(log_path)
            ):
                logger.info(
                    "[%s] %s crashed (rc=%d) with a blow-up signature → "
                    "halve dt and restart",
                    job.job_id,
                    spec.name,
                    rc,
                )
                _halve_dt_and_restart(job, workspace_dir, specs, idx)
                continue
            # Otherwise: if it's at/after the relax stage and retry budget
            # remains, escalate the relax and retry the hand-off (the canonical case:
            # a standard-potential stage aborting at config load on a residual
            # over-stretched backbone bond).
            if (
                relax_idx is not None
                and idx >= relax_idx
                and job.relax_retries < job.max_relax_retries
            ):
                logger.info(
                    "[%s] %s crashed (rc=%d) → retry via escalated relax",
                    job.job_id,
                    spec.name,
                    rc,
                )
                _escalate_relax_and_rewind(
                    job, workspace_dir, specs, relax_idx, base_relax_spec
                )
                idx = relax_idx
                continue
            job.stages[idx].status = "failed"
            job.status = OxdnaStatus.failed
            if spec.kind in _DT_HALVE_KINDS and _log_indicates_explosion(log_path):
                job.error = (
                    f"{spec.name} kept going numerically unstable (the structure's "
                    f"coordinates blew up) even after {job.max_production_retries} "
                    f"automatic timestep reduction(s), down to dt={spec.dt}. The design "
                    f"is likely too floppy or strained to sample — relaxing it longer, "
                    f"or stiffening the structure (e.g. fewer/shorter single-stranded "
                    f"extra bases at crossovers), is the likely fix."
                )
            else:
                job.error = (
                    f"oxDNA failed for {spec.name} (rc={rc}). See {spec.name}/oxdna.log"
                )
            job.save(workspace_dir)
            return

        # ── Health check + gate (oxDNA HBList ground truth when available) ────
        # Mainline DNAnalysis can't parse a hybrid DNANM topology, so protein jobs
        # use the geometric base-pair-retention metric (now hybrid-index-aware via
        # read_configuration_full's protein-lead offset).
        res = run_oxdna_health_check(
            design,
            stage_dir,
            kind=spec.kind,
            min_bp_retained=spec.min_bp_retained,
            topology_path=topo,
            dnanalysis_bin=None if is_hybrid else find_dnanalysis(),
            salt_concentration=spec.salt_concentration,
            # Surface capture strands are appended AFTER the design walk; without this
            # the reader mistakes them for a leading protein block and every geometric
            # metric is computed on the wrong particles (see run_oxdna_health_check).
            n_trailing_extra=capture_bead_count(job),
        )
        steps_per_s = spec.steps / elapsed
        sample = _health_sample(spec.name, spec.kind, res, steps_per_s)
        job.health_samples.append(sample)
        _append_jsonl(jd / "health.jsonl", asdict(sample))
        _append_jsonl(
            jd / "metrics.jsonl",
            {
                "wall_time": time.time(),
                "stage": spec.name,
                "kind": spec.kind,
                "steps": spec.steps,
                "elapsed_s": elapsed,
                "steps_per_s": steps_per_s,
                "potential_energy": res.potential_energy,
                "energy_converged": res.energy_converged,
            },
        )

        logger.info(
            "[%s] %s health: bp=%s clash=%s passed=%s",
            job.job_id,
            spec.name,
            f"{res.bp_retained_fraction:.2f}"
            if res.bp_retained_fraction is not None
            else "—",
            res.n_clashes,
            res.passed,
        )

        if not res.passed:
            # A base-pair melt (or a numerical blow-up) at md_relax is RECOVERABLE, not
            # terminal: the escalation ladder (more steps + a smaller timestep) gives the
            # trap-held pairs time to anneal into register instead of fraying, and a
            # smaller dt stops the first-step velocity refresh from kicking borderline
            # pairs apart.  Spend a retry on it — the same lever + budget the FENE gate
            # uses — rather than giving up.  This keeps oxDNA fast: the quick default
            # relax still runs first, and only a failed melt pays for the longer,
            # gentler escalated pass.
            if (
                spec.kind == "md_relax"
                and relax_idx is not None
                and job.relax_retries < job.max_relax_retries
            ):
                logger.info(
                    "[%s] %s health gate failed (%s) → retry via escalated relax",
                    job.job_id,
                    spec.name,
                    res.reason,
                )
                _escalate_relax_and_rewind(
                    job, workspace_dir, specs, relax_idx, base_relax_spec
                )
                idx = relax_idx
                continue
            job.stages[idx].status = "failed"
            job.status = OxdnaStatus.failed
            if spec.kind == "md_relax" and job.max_relax_retries > 0:
                job.error = (
                    f"Relaxation could not hold the structure together after "
                    f"{job.max_relax_retries} escalating attempt(s): {res.reason}. The "
                    f"design is over-strained for this coarse seed — relaxing longer, "
                    f"lowering dt, or simplifying the geometry is the likely fix."
                )
            else:
                job.error = (
                    f"Health gate failed after {spec.name}: {res.reason or res.error}"
                )
            job.save(workspace_dir)
            return

        # ── FENE equil-readiness gate (escalate-and-retry) ───────────────────
        # md_relax passed its bp gate but left a backbone bond past oxDNA's FENE
        # cliff: the structure isn't ready for the standard-potential equil.  Spend a
        # retry on an escalated relax; once the budget is exhausted, stop with a clear
        # failure rather than equilibrating a strained structure.
        if spec.kind == "md_relax" and not res.fene_safe:
            if job.relax_retries < job.max_relax_retries:
                _escalate_relax_and_rewind(
                    job, workspace_dir, specs, relax_idx, base_relax_spec
                )
                idx = relax_idx
                continue
            if job.max_relax_retries > 0:
                job.stages[idx].status = "failed"
                job.status = OxdnaStatus.failed
                mx = res.max_backbone_fene_units or 0.0
                job.error = (
                    f"Relaxation could not bring all backbone bonds within oxDNA's "
                    f"FENE range after {job.max_relax_retries} escalating attempt(s) "
                    f"({res.n_fene_over} bond(s) over-stretched, longest {mx:.3f} units "
                    f"vs the {FENE_RMAX_UNITS:.3f} cliff). The structure is over-strained "
                    f"— relaxing without the surface/anchor traps, lowering dt, or "
                    f"simplifying the geometry is the likely fix."
                )
                job.save(workspace_dir)
                return
            # max_relax_retries == 0 → legacy behaviour: proceed to the (capped) equil,
            # which tolerates the residual over-stretch rather than crashing.
            logger.info(
                "[%s] %s not equil-ready (%d over-stretched) but retries "
                "disabled → proceeding to capped equil",
                job.job_id,
                spec.name,
                res.n_fene_over,
            )

        # ── Non-aborting blow-up gate (extend dt-halving to silent explosions) ──
        # An unbiased sampling stage can go numerically unstable and BALLOON the
        # structure without ever tripping oxDNA's hard abort (it exits 0).  The health
        # check above can still pass (bp can stay paired while the bundle swells), so
        # without this the job would finish "done" with a blown-apart structure that
        # display / autorefine then measures.  Treat it exactly like a crash blow-up:
        # halve dt and re-run from the relaxed seed; fail clearly once the budget is out.
        if spec.kind in _BLOWUP_EXTENT_KINDS and _structure_blew_up(stage_dir, conf):
            if job.production_retries < job.max_production_retries:
                logger.info(
                    "[%s] %s completed but the structure blew up (extent > %.1f× "
                    "the relaxed seed) → halve dt and restart",
                    job.job_id,
                    spec.name,
                    _EXPLOSION_EXTENT_FACTOR,
                )
                _halve_dt_and_restart(job, workspace_dir, specs, idx)
                continue
            job.stages[idx].status = "failed"
            job.status = OxdnaStatus.failed
            job.error = (
                f"{spec.name} finished but the structure blew up (it expanded far beyond "
                f"its relaxed size) even after {job.max_production_retries} automatic "
                f"timestep reduction(s), down to dt={spec.dt}. The design is likely too "
                f"floppy/strained to sample at this timestep — relax it longer or lower dt."
            )
            job.save(workspace_dir)
            return

        # Surface contact is asynchronous: on a large origami some anchors arrive
        # while others are still several nanometres away.  Gate every completed
        # approach window, retain arrivals with normal-only traps, and continue from
        # the checkpoint with a bounded force ramp on only the remaining anchors.
        if spec.kind == "deposition_approach":
            rcfg = job.run_config or {}
            contact_forces = jd / "deposition_settle_forces.txt"
            contact_forces.unlink(missing_ok=True)
            try:
                write_surface_deposition_settle_forces(
                    contact_forces,
                    design,
                    stage_dir / "last_conf.dat",
                    wall=rcfg["surface"],
                    anchors=rcfg.get("surface_anchors") or [],
                    anchor_stiff=float(rcfg.get("surface_anchor_stiff", 1.0)),
                    max_contact_gap_nm=float(rcfg.get("contact_gap_nm", 0.75)),
                )
            except (KeyError, ValueError) as exc:
                retry = int(rcfg.get("approach_retry_count", 0))
                max_windows = int(rcfg.get("max_approach_windows", 8))
                if retry >= max_windows:
                    job.stages[idx].status = "failed"
                    job.status = OxdnaStatus.failed
                    job.error = f"cannot prepare surface-contact restraints: {exc}"
                    job.save(workspace_dir)
                    return
                base_force = float(rcfg.get("approach_force_pn", 5.0))
                force_ceiling = float(rcfg.get("max_approach_force_pn", 20.0))
                force_pn = min(force_ceiling, base_force * (2 ** (retry + 1)))
                info = write_surface_deposition_approach_forces(
                    jd / "deposition_approach_forces.txt",
                    design,
                    stage_dir / "last_conf.dat",
                    wall=rcfg["surface"],
                    anchors=rcfg.get("surface_anchors") or [],
                    force_pn=force_pn,
                    capture_contacted=True,
                    capture_gap_nm=float(rcfg.get("capture_gap_nm", 1.0)),
                    capture_stiff=float(rcfg.get("surface_anchor_stiff", 1.0)),
                )
                window = int(rcfg.get("approach_retry_chunk_steps", 50_000))
                total_spec = specs[idx]
                specs[idx] = replace(
                    total_spec,
                    steps=total_spec.steps + window,
                    print_energy_every_override=(
                        total_spec.print_energy_every_override
                        or max(1, total_spec.steps // 100)
                    ),
                )
                job.stages[idx].steps = specs[idx].steps
                job.stages[idx].status = "pending"
                job.stages[idx].started_at = None
                job.current_stage_idx = idx
                rcfg["approach_retry_count"] = retry + 1
                rcfg["approach_retry_force_pn"] = force_pn
                rcfg["approach_retry_max_gap_nm"] = info["max_initial_gap_nm"]
                rcfg["approach_retry_captured"] = info["n_captured"]
                rcfg["approach_retry_remaining"] = len(info["remaining_particles"])
                job.run_config = rcfg
                _persist_specs(job, workspace_dir, specs)
                job.save(workspace_dir)
                start_idx = idx
                logger.info(
                    "[%s] surface contact incomplete (%s) -> adaptive window %d/%d; "
                    "%d captured, %d remaining, force %.3g pN",
                    job.job_id, exc, retry + 1, max_windows,
                    info["n_captured"], len(info["remaining_particles"]), force_pn,
                )
                continue

        job.stages[idx].status = "done"
        job.current_stage_idx = idx + 1
        job.save(workspace_dir)
        idx += 1

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
    (job.job_dir(workspace_dir) / _STOP_MARKER).unlink(missing_ok=True)

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

    thread = threading.Thread(
        target=_thread_main, name=f"oxdna-runner-{job.job_id}", daemon=True
    )
    _RUNNING[job.job_id] = _RunningHandle(thread=thread)
    thread.start()


def _pid_is_oxdna(pid: int) -> bool:
    """True if /proc/<pid> is a live oxDNA process (guards against a recycled PID)."""
    try:
        cmdline = (Path("/proc") / str(pid) / "cmdline").read_bytes().lower()
    except OSError:
        return False
    return b"oxdna" in cmdline


def stop_job(job_id: str, workspace_dir: Path) -> bool:
    """Cancel the running task for job_id. Returns True if a task was found.

    Like NAMD: the in-process path cancels the runner task + kills its group; the
    ORPHAN path (server restarted → registry empty, but a detached oxDNA may still be
    running) finds the orphan via /proc (self-verifying) or the persisted ``oxdna_pid``,
    kills it, and marks the job stopped so it stays controllable."""
    handle = _RUNNING.get(job_id)
    if handle and handle.thread.is_alive():
        try:
            live_job = OxdnaJob.load(job_id, workspace_dir)
            (live_job.job_dir(workspace_dir) / _STOP_MARKER).touch()
        except Exception:  # noqa: BLE001
            pass
        pid = _ACTIVE_PIDS.get(job_id)
        if pid:
            _kill_process_group(pid)
        if handle.loop is not None and handle.task is not None:
            try:
                handle.loop.call_soon_threadsafe(handle.task.cancel)
            except RuntimeError:
                # The stop marker can make the runner finish while SIGTERM is being
                # delivered; a concurrently closed loop already achieved the stop.
                pass
        return True

    # Orphan fallback: no live runner thread, but a detached process may persist.
    try:
        job = OxdnaJob.load(job_id, workspace_dir)
    except Exception:  # noqa: BLE001
        return False
    if job.status != OxdnaStatus.running:
        return False
    pid = _external_oxdna_pid(job, workspace_dir)
    if pid is None and job.oxdna_pid and _pid_is_oxdna(job.oxdna_pid):
        pid = job.oxdna_pid
    if pid is None:
        return False
    (job.job_dir(workspace_dir) / _STOP_MARKER).touch()
    _kill_process_group(pid)
    job.status = OxdnaStatus.stopped
    job.oxdna_pid = None
    job.save(workspace_dir)
    return True


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
    if _external_oxdna_running(job, workspace_dir):
        return job  # orphaned but still alive on disk/GPU — keep it running
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
        complete = (sdir / "last_conf.dat").exists() and _stage_energy_lines(
            sdir
        ) >= expected
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
