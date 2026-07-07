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
from backend.physics.oxdna_interface import (
    surface_anchor_forces_text,
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
                [ldd, path], capture_output=True, text=True, timeout=15, check=False,
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
        candidate if os.path.isfile(candidate) and os.access(candidate, os.X_OK) else None
    )


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
    os.path.expanduser("~/anm-oxdna/oxDNA/build_cuda/bin/oxDNA"),   # CUDA (preferred)
    os.path.expanduser("~/anm-oxdna/oxDNA/build/bin/oxDNA"),        # CPU fallback
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


# ── LAMMPS (CG-DNA / oxDNA) discovery ─────────────────────────────────────────
#
# LAMMPS with the CG-DNA package runs the *same* oxDNA/oxDNA2 force field as the
# standalone oxDNA above, but MPI domain-decomposed — the only oxDNA that scales
# to very large assemblies on CPU cores.  It is a SEPARATE binary (``lmp``), and
# only a build that included the CG-DNA package can run the oxDNA styles, so it is
# discovered + capability-probed independently (mirrors find_oxdna /
# oxdna_supports_cuda).  The runner that uses it is a later phase.

_LAMMPS_CANDIDATES = [
    "lmp",                                                        # modern default name
    "lmp_mpi",
    "lmp_serial",
    os.path.expanduser("~/lammps/build/lmp"),                    # conventional source build
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
            [path, "-h"], capture_output=True, text=True, timeout=20, check=False,
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
    design:        Design,
    geometry:      list[dict],
    job:           OxdnaJob,
    workspace_dir: Path,
    specs:         list[OxdnaStageSpec],
    *,
    surface:       dict | None = None,
    anchors:       list[dict] | None = None,
    anchor_stiff:  float = 1000.0,
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
        (jd / "topology.top").write_text(hybrid_topology_text(design, blocks), encoding="utf-8")
        (jd / "conf.dat").write_text(
            hybrid_configuration_text(design, geometry, blocks, oxdna_native_seed=True),
            encoding="utf-8")
        (jd / "anm.par").write_text(anm_par_text(blocks), encoding="utf-8")
        prot_traps = protein_forces_text(design, atts, blocks, geometry)
    else:
        write_topology(design, jd / "topology.top")
        write_configuration(design, geometry, jd / "conf.dat", oxdna_native_seed=True)

    # Optional hard surface + anchors held throughout the relax (a structure relaxed
    # on a surface differs from one relaxed free).
    sa_text, info = "", {}
    if surface or anchors:
        sa_text, info = surface_anchor_forces_text(
            design, jd / "conf.dat", wall=surface, anchors=anchors, anchor_stiff=anchor_stiff)
    # The equil stage drops the DNA mutual traps but keeps surface/anchors AND the
    # protein tethers (so proteins don't drift off the structure during the unbiased
    # settle).  Write it whenever either is present (the spec references it).
    equil_extra = "\n".join(t for t in (sa_text, prot_traps) if t)
    if surface or anchors or protein:
        (jd / "equil_forces.txt").write_text(equil_extra, encoding="utf-8")
    # Mutual-trap external forces (hold designed WC pairs during the relax stages —
    # NADOC geometry starts the pairs outside oxDNA's H-bond range, so without this
    # a free MD melts the structure) + the surface/anchor + protein-tether blocks.
    write_mutual_traps(design, jd / "forces.txt",
                       extra_text=equil_extra, particle_offset=prot_offset)
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

    # Recenter the seed on the origin.  oxDNA does NOT fix the centre of mass, so a
    # relaxed conf can sit hundreds of nm out (COM diffusion over the run); the
    # reconstruction faithfully reproduces that absolute position.  Absolute position
    # is irrelevant for a boxed MD seed, but the exported PDB's 8-char coordinate
    # fields overflow past ~±1000 Å — the file silently corrupts and the downstream
    # ENM base-ring scan finds no atoms.  Translate every atom by the model centroid.
    if model.atoms:
        import numpy as _np
        cx, cy, cz = _np.mean(
            [[a.x, a.y, a.z] for a in model.atoms], axis=0).tolist()
        for a in model.atoms:
            a.x -= cx
            a.y -= cy
            a.z -= cz

    return NamdSeed(
        design          = design,
        atomistic_model = model,
        stage_name      = stage_name,
        conf_path       = conf_path,
        source_job_id   = job_id,
    )


def assert_namd_seed_available(job_id: str, workspace_dir: Path) -> None:
    """Cheap precheck that a NAMD seed CAN be built from this oxDNA job.

    Verifies the job exists and has both a ``design.json`` snapshot and a relaxed
    ``last_conf.dat`` — WITHOUT the expensive atomistic reconstruction.  Lets the
    create-job route reject a bad ``oxdna_job_id`` with a fast 400 before any work
    is queued, while the real (slow) :func:`build_namd_seed` runs in the
    background.  Raises FileNotFoundError with a user-facing message otherwise.
    """
    job = OxdnaJob.load(job_id, workspace_dir)   # FileNotFoundError if unknown
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
    from backend.physics.oxdna_interface import read_trajectory_frames_full

    out: dict = {
        "bp_retained_fraction": None, "potential_energy": None,
        "max_backbone_clash": None, "steps_per_s": steps_per_s,
    }
    try:
        samples = parse_energy_dat(stage_dir / "energy.dat")
        if samples:
            out["potential_energy"] = samples[-1][1]
    except Exception:
        pass
    try:
        frames = read_trajectory_frames_full(stage_dir / "trajectory.dat", design)
        if frames:
            frame = frames[-1]
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
        return 5.0                                   # CPU Monte-Carlo sweeps/s
    return 1000.0 if (backend or "").upper() == "CUDA" else 400.0   # MD steps/s


def job_progress(job: OxdnaJob, workspace_dir: Path, specs: list[OxdnaStageSpec]) -> dict:
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
            stage_frac = min(1.0, lines / max(1, expected_energy_lines(specs[idx])))

            # ── ETA: sum each remaining stage estimated with ITS OWN rate class ───
            # Mixing the slow MC rate with the (1e6-step) MD stages is the bug that
            # showed ">100 h" during MC — estimate per class (MC vs MD-family) instead.
            steps_done = stage_frac * specs[idx].steps
            live_rate = None
            if st.started_at and steps_done > 0:
                live_rate = steps_done / max(1e-6, time.time() - st.started_at)

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

            eta_seconds = max(0.0, _seconds(idx, specs[idx].steps - steps_done) + sum(
                _seconds(j, specs[j].steps) for j in range(idx + 1, len(specs))
            ))

            # ── Time to the next DISPLAY frame (last_conf/trajectory write) ───────
            # The relaxed display follows the run live; a new frame lands every
            # print_conf_interval steps.  Estimate the wait to the next one from the
            # current stage's rate so the panel can count it down.
            interval = print_conf_interval(specs[idx])
            frame_index = int(steps_done // interval)
            steps_to_next = (frame_index + 1) * interval - steps_done
            steps_to_next = min(steps_to_next, specs[idx].steps - steps_done)
            cur_rate = (live_rate if live_rate and live_rate > 0
                        else rate_by_class.get(_rate_class(specs[idx].kind))
                        or _default_stage_rate(specs[idx], job.backend))
            if cur_rate and cur_rate > 0:
                next_frame_eta_seconds = max(0.0, steps_to_next / cur_rate)

            # ── Live health snapshot (advisory; cards tick mid-stage) ─────────────
            design = _load_snapshot_design(job.job_dir(workspace_dir))
            if design is not None:
                live_health = _live_health_snapshot(
                    design, stage_dir, live_rate or rate_by_class.get(_rate_class(specs[idx].kind)))
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
    log_path:  Path,
    job_id:    str,
    on_spawn=None,
) -> tuple[int, Optional[int]]:
    """Run oxDNA on *input_path* with cwd=stage_dir; return (returncode, pid).

    ``on_spawn(pid)`` fires right after the process starts (and ``on_spawn(None)`` on
    exit) so the caller can persist the PID to job.json — surviving a server restart so
    ``stop_job`` can signal an orphaned run."""
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
        if on_spawn:
            try: on_spawn(pid)
            except Exception: pass  # noqa: E722,S110 — persistence must never break the run
        try:
            rc = await wait_proc_with_disk_guard(proc, stage_dir, kill=_kill_process_group)
        except asyncio.CancelledError:
            _kill_process_group(pid)
            raise
        finally:
            _ACTIVE_PIDS.pop(job_id, None)
            if on_spawn:
                try: on_spawn(None)
                except Exception: pass  # noqa: E722,S110
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
        max_backbone_fene    = res.max_backbone_fene_units,
        steps_per_s          = steps_per_s,
        passed               = res.passed,
        reason               = res.reason or (res.error or ""),
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
    own_last = (job.stage_dir(workspace_dir, specs[idx].name) / "last_conf.dat").resolve()
    if idx == start_idx and own_last.exists() and own_last.stat().st_size > 0:
        return own_last
    if idx == 0:
        return (job.job_dir(workspace_dir) / "conf.dat").resolve()
    return (job.stage_dir(workspace_dir, specs[idx - 1].name) / "last_conf.dat").resolve()


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

def _persist_specs(job: OxdnaJob, workspace_dir: Path, specs: list[OxdnaStageSpec]) -> None:
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
        job.stages[i].status     = "pending"
        job.stages[i].started_at = None
        job.stages[i].resumed    = False
        job.stages[i].steps      = specs[i].steps
        _reset_stage_outputs(job.stage_dir(workspace_dir, specs[i].name))
    job.current_stage_idx = relax_idx
    _persist_specs(job, workspace_dir, specs)
    job.save(workspace_dir)
    logger.info("[%s] relax not equil-ready → escalating md_relax (attempt %d/%d): "
                "steps=%d dt=%s cap=%s; rewinding to %s",
                job.job_id, job.relax_retries, job.max_relax_retries,
                specs[relax_idx].steps, specs[relax_idx].dt,
                specs[relax_idx].max_backbone_force, specs[relax_idx].name)


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
    "_max_n_per_cell",                      # cell list overflow from huge coordinates
    "particles with very large coordinates",
    "nan",                                  # NaN energy/coordinate
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
    for ln in lines[3:]:                       # skip the t= / b= / E= header lines
        p = ln.split()
        if len(p) < 3:
            continue
        try:
            xyz = (float(p[0]), float(p[1]), float(p[2]))
        except ValueError:
            continue
        if not all(math.isfinite(v) for v in xyz):
            return float("inf")                # NaN/inf coordinate = definitely blown up
        seen = True
        for i in range(3):
            lo[i] = min(lo[i], xyz[i]); hi[i] = max(hi[i], xyz[i])
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
    job.stages[idx].status     = "pending"
    job.stages[idx].started_at = None
    job.stages[idx].resumed    = False
    _reset_stage_outputs(job.stage_dir(workspace_dir, specs[idx].name))
    job.current_stage_idx = idx
    _persist_specs(job, workspace_dir, specs)
    job.save(workspace_dir)
    logger.info("[%s] %s went unstable (coordinate blow-up) → halving dt and "
                "restarting from the relaxed seed (attempt %d/%d): dt=%s",
                job.job_id, specs[idx].name, job.production_retries,
                job.max_production_retries, specs[idx].dt)


# ── Main runner coroutine ─────────────────────────────────────────────────────

async def run_job(job: OxdnaJob, workspace_dir: Path, specs: list[OxdnaStageSpec]) -> None:
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
            ("ANM-oxDNA (protein) binary not found. Set $OXDNA_ANM_BIN or run "
             "scripts/build-anm-oxdna.sh.") if is_hybrid else
            "oxDNA binary not found. Set $OXDNA_BIN or install to ~/oxDNA/build/bin/oxDNA.")
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
            archived = _archive_partial_outputs(stage_dir)
            job.stages[idx].resumed = True
            logger.info("[%s] resuming stage %s from its own checkpoint last_conf.dat "
                        "(archived partial outputs: %s)",
                        job.job_id, spec.name, ", ".join(archived) or "none")

        input_path = stage_dir / "input.txt"
        # Relax stages use the default mutual-trap forces.txt; a field stage points
        # spec.forces_file at its own field_forces_N.txt (uniform force + anchors).
        forces = (jd / (spec.forces_file or "forces.txt")).resolve() if spec.external_forces else None
        # The ANM parameter file (hybrid stages) is resolved to an absolute path in
        # the job dir, like topology/conf/forces (oxDNA runs with cwd=stage_dir).
        parfile = str((jd / spec.parfile).resolve()) if spec.parfile else None
        input_path.write_text(
            render_stage_input(spec, str(topo), str(conf),
                               forces_name=str(forces) if forces else None,
                               parfile_name=parfile)
        )

        logger.info("[%s] stage %d/%d: %s (%s, %d steps)",
                    job.job_id, idx + 1, len(specs), spec.name, spec.kind, spec.steps)
        job.current_stage_idx = idx
        job.stages[idx].status = "running"
        job.stages[idx].started_at = time.time()
        job.save(workspace_dir)

        _fb = free_bytes(stage_dir)
        if _fb < ABORT_MIN_FREE_BYTES:
            logger.error("[%s] Refusing to start %s: only %.1f GB free (floor %.0f GB)",
                         job.job_id, spec.name, _fb / GiB, ABORT_MIN_FREE_BYTES / GiB)
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
        rc, pid = await _run_oxdna_async(oxdna_bin, input_path, stage_dir, log_path, job.job_id,
                                         on_spawn=_persist_pid)
        elapsed = max(1e-6, time.time() - t0)

        if asyncio.current_task().cancelled():
            if pid:
                _kill_process_group(pid)
            raise asyncio.CancelledError

        if rc == DISK_ABORT_RC:
            fb = free_bytes(stage_dir)
            logger.error("[%s] Disk guard aborted %s: %.1f GB free",
                         job.job_id, spec.name, fb / GiB)
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
            if (spec.kind in _DT_HALVE_KINDS
                    and job.production_retries < job.max_production_retries
                    and _log_indicates_explosion(log_path)):
                logger.info("[%s] %s crashed (rc=%d) with a blow-up signature → "
                            "halve dt and restart", job.job_id, spec.name, rc)
                _halve_dt_and_restart(job, workspace_dir, specs, idx)
                continue
            # Otherwise: if it's at/after the relax stage and retry budget
            # remains, escalate the relax and retry the hand-off (the canonical case:
            # a standard-potential stage aborting at config load on a residual
            # over-stretched backbone bond).
            if (relax_idx is not None and idx >= relax_idx
                    and job.relax_retries < job.max_relax_retries):
                logger.info("[%s] %s crashed (rc=%d) → retry via escalated relax",
                            job.job_id, spec.name, rc)
                _escalate_relax_and_rewind(job, workspace_dir, specs, relax_idx, base_relax_spec)
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
                job.error = f"oxDNA failed for {spec.name} (rc={rc}). See {spec.name}/oxdna.log"
            job.save(workspace_dir)
            return

        # ── Health check + gate (oxDNA HBList ground truth when available) ────
        # Mainline DNAnalysis can't parse a hybrid DNANM topology, so protein jobs
        # use the geometric base-pair-retention metric (now hybrid-index-aware via
        # read_configuration_full's protein-lead offset).
        res = run_oxdna_health_check(
            design, stage_dir, kind=spec.kind, min_bp_retained=spec.min_bp_retained,
            topology_path=topo,
            dnanalysis_bin=None if is_hybrid else find_dnanalysis(),
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
            # A base-pair melt (or a numerical blow-up) at md_relax is RECOVERABLE, not
            # terminal: the escalation ladder (more steps + a smaller timestep) gives the
            # trap-held pairs time to anneal into register instead of fraying, and a
            # smaller dt stops the first-step velocity refresh from kicking borderline
            # pairs apart.  Spend a retry on it — the same lever + budget the FENE gate
            # uses — rather than giving up.  This keeps oxDNA fast: the quick default
            # relax still runs first, and only a failed melt pays for the longer,
            # gentler escalated pass.
            if (spec.kind == "md_relax" and relax_idx is not None
                    and job.relax_retries < job.max_relax_retries):
                logger.info("[%s] %s health gate failed (%s) → retry via escalated relax",
                            job.job_id, spec.name, res.reason)
                _escalate_relax_and_rewind(job, workspace_dir, specs, relax_idx, base_relax_spec)
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
                job.error = f"Health gate failed after {spec.name}: {res.reason or res.error}"
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
                    job, workspace_dir, specs, relax_idx, base_relax_spec)
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
            logger.info("[%s] %s not equil-ready (%d over-stretched) but retries "
                        "disabled → proceeding to capped equil",
                        job.job_id, spec.name, res.n_fene_over)

        # ── Non-aborting blow-up gate (extend dt-halving to silent explosions) ──
        # An unbiased sampling stage can go numerically unstable and BALLOON the
        # structure without ever tripping oxDNA's hard abort (it exits 0).  The health
        # check above can still pass (bp can stay paired while the bundle swells), so
        # without this the job would finish "done" with a blown-apart structure that
        # display / autorefine then measures.  Treat it exactly like a crash blow-up:
        # halve dt and re-run from the relaxed seed; fail clearly once the budget is out.
        if spec.kind in _BLOWUP_EXTENT_KINDS and _structure_blew_up(stage_dir, conf):
            if job.production_retries < job.max_production_retries:
                logger.info("[%s] %s completed but the structure blew up (extent > %.1f× "
                            "the relaxed seed) → halve dt and restart",
                            job.job_id, spec.name, _EXPLOSION_EXTENT_FACTOR)
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
        pid = _ACTIVE_PIDS.get(job_id)
        if pid:
            _kill_process_group(pid)
        if handle.loop is not None and handle.task is not None:
            handle.loop.call_soon_threadsafe(handle.task.cancel)
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
