"""GPU-VRAM failure detection and downsize recommendation for NAMD jobs.

A large explicit-solvent origami can exceed the GPU's memory and abort with a
CUDA ``out of memory`` error at startup.  This module:

  1. recognises that failure in a NAMD log (:func:`log_indicates_oom`),
  2. reads the GPU's total VRAM (:func:`detect_vram_mb`),
  3. estimates whether a *more restrictive* run (a tighter water-shell carve, see
     ``namd_solvate._carve_water_shell``) would fit, and which shell to use
     (:func:`recommend_downsize`).

The VRAM model is empirical: NAMD standard-CUDA peaked at ~4.0 GB for a 1.31 M
atom system on a 12 GB RTX 3080 Ti, and an 8.86 M atom system OOM'd on the same
card.  We round the per-atom cost up so a recommended downsize fits with headroom
rather than OOM-ing a second time.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

# ── Empirical VRAM model ──────────────────────────────────────────────────────
# Peak GPU memory ≈ _MB_PER_MATOM per million atoms (NAMD 3 standard CUDA).
# Observed ~4.0 GB at 1.31 M atoms → ~3.05 GB/M; rounded up to 3.3 for safety.
_MB_PER_MATOM = 3300.0
# Leave VRAM for the display server, driver context and allocator fragmentation.
_USABLE_FRACTION = 0.85
# Bulk TIP3P number density (waters/nm³); see namd_solvate._WATER_NUMBER_DENSITY_NM3.
_WATER_NUMBER_DENSITY_NM3 = 33.4
# Effective density when filling the *whole* box (lower than bulk: the DNA volume
# and packing reduce the count).  Calibrated to observed gmx solvate runs
# (VoltronCore: 2.79 M waters in 90 k nm³ ≈ 31; ideal build ≈ 30).  Used only for
# the pre-flight size estimate, where no gmx run is available yet.
_FULL_BOX_WATER_DENSITY_NM3 = 30.0

# Candidate hydration-shell thicknesses (nm), largest (least restrictive) first.
# 2·shell must clear the 12 Å nonbonded cutoff for a valid minimum image, so the
# smallest candidate is 0.8 nm (16 Å gap).
CANDIDATE_SHELLS_NM = (2.0, 1.8, 1.5, 1.2, 1.0, 0.8)

_OOM_PAT = re.compile(r"out of memory", re.IGNORECASE)
# A freshly built model that blows up on the first dynamics steps.
_INSTABILITY_PAT = re.compile(
    r"Constraint failure|Margin is too small|atoms? moving too fast|"
    r"bad global (?:bond|angle|exclusion) count|velocity.*too (?:large|high)|"
    r"ERROR: Atoms moving",
    re.IGNORECASE,
)
# A GPU/driver/kernel error that is not an out-of-memory condition.
_GPU_ERR_PAT = re.compile(r"buildTileLists|cudaStreamSynchronize|CUDA error", re.IGNORECASE)
# NPT equilibration shrank the box past the patch grid built at startup. This is
# NOT a blow-up (energies stay healthy) — restarting from the last checkpoint
# rebuilds the grid for the smaller box and continues, so it is auto-resumable.
_CELL_SHRINK_PAT = re.compile(r"Periodic cell has become too small", re.IGNORECASE)

# Known failure kinds (also the keys the UI maps to a remedy).
FAILURE_VRAM_OOM = "vram_oom"
FAILURE_INSTABILITY = "instability"
FAILURE_GPU_ERROR = "gpu_error"
FAILURE_CELL_SHRINK = "cell_shrink"
FAILURE_OTHER = "other"


# ══════════════════════════════════════════════════════════════════════════════
# §1  FAILURE DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def log_indicates_oom(text: str) -> bool:
    """True if a NAMD log contains a CUDA out-of-memory abort."""
    return bool(_OOM_PAT.search(text))


def classify_failure_log(text: str) -> str:
    """Classify a NAMD failure log into a FAILURE_* kind.

    Order matters: an OOM abort also prints "CUDA error", so it is matched first;
    a RATTLE/margin blow-up is matched before the generic GPU-error pattern. The
    cell-shrink fatal has a unique string and does not overlap the others.
    """
    if _OOM_PAT.search(text):
        return FAILURE_VRAM_OOM
    if _INSTABILITY_PAT.search(text):
        return FAILURE_INSTABILITY
    if _GPU_ERR_PAT.search(text):
        return FAILURE_GPU_ERROR
    if _CELL_SHRINK_PAT.search(text):
        return FAILURE_CELL_SHRINK
    return FAILURE_OTHER


def _read_log_tail(path: Path, n: int = 20_000) -> str:
    try:
        return path.read_text(errors="replace")[-n:]
    except OSError:
        return ""


def log_file_indicates_oom(path: Path) -> bool:
    """True if the NAMD log *file* contains an out-of-memory abort (tail only)."""
    return log_indicates_oom(_read_log_tail(path))


def classify_failure_log_file(path: Path) -> str:
    """Classify a NAMD log *file* (tail only) into a FAILURE_* kind."""
    return classify_failure_log(_read_log_tail(path))


# Log lines that carry the human-meaningful *cause* of a failure, most-specific
# first: a NAMD ``FATAL ERROR:`` wins over a generic ``ERROR:`` even if the latter
# appears earlier.  Covers both NAMD-level (FATAL ERROR / abort) and SLURM-level
# (time-limit / OOM cancellation, ``slurmstepd``/``srun`` errors, a ``set -u``
# unbound-variable abort in the job header).
_CAUSE_LINE_PATS = (
    re.compile(r"^.*FATAL ERROR:.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*DUE TO (?:TIME LIMIT|NODE FAILURE|PREEMPTION|JOB REQUEUE).*$",
               re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*(?:oom-kill|out of memory|outofmemory).*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*slurmstepd:\s*error:.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*srun:\s*error:.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*unbound variable.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*\bABORT(?:ING)?\b.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*\bERROR:.*$", re.IGNORECASE | re.MULTILINE),
)

_MAX_EXCERPT = 300


def extract_error_line(text: str) -> Optional[str]:
    """Most-informative single error line from a NAMD/SLURM log, or None.

    Scans known fatal markers most-specific-first (NAMD ``FATAL ERROR:``, SLURM
    time-limit / OOM cancellations, ``slurmstepd``/``srun`` errors, a ``set -u``
    unbound-variable abort, then a generic ``ERROR:``).  Returned trimmed + capped
    so it fits a one-line status message on the frontend.
    """
    for pat in _CAUSE_LINE_PATS:
        m = pat.search(text or "")
        if m:
            return m.group(0).strip()[:_MAX_EXCERPT]
    return None


def extract_error_line_from_file(path: Path) -> Optional[str]:
    """:func:`extract_error_line` over a log *file* (tail only)."""
    return extract_error_line(_read_log_tail(path))


# ══════════════════════════════════════════════════════════════════════════════
# §2  VRAM DETECTION + MODEL
# ══════════════════════════════════════════════════════════════════════════════

def _first_device_id(devices: str) -> int:
    """First CUDA device id from a NAMD ``devices`` string (e.g. '0' or '0,1')."""
    try:
        return int(str(devices).split(",")[0].strip())
    except (ValueError, AttributeError, IndexError):
        return 0


def detect_vram_mb(devices: str = "0") -> Optional[int]:
    """Total VRAM (MB) of the job's first CUDA device, or None if unavailable."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    dev = _first_device_id(devices)
    try:
        out = subprocess.run(
            [exe, f"--id={dev}", "--query-gpu=memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return int(out.stdout.strip().splitlines()[0].strip())
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


# A compute process holding at least this much VRAM counts as "GPU-intensive" —
# enough to flag a background NAMD/GROMACS/oxDNA run while ignoring incidentals
# like a remote-desktop server's small context.
_GPU_BUSY_PROC_MB = 500


def detect_gpu_activity(devices: str = "0") -> Optional[dict]:
    """Current GPU load: memory, utilisation and the compute processes using it.

    Returns ``{used_mb, total_mb, free_mb, util_pct, processes:[{pid, name,
    mem_mb}]}`` or ``None`` if ``nvidia-smi`` is unavailable.  ``name`` is the
    process basename (e.g. ``namd3``).  Best-effort — any query failure yields
    ``None`` so callers can degrade to "unknown / proceed".
    """
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    dev = _first_device_id(devices)
    try:
        mem = subprocess.run(
            [exe, f"--id={dev}", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        apps = subprocess.run(
            [exe, "--query-compute-apps=pid,process_name,used_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if mem.returncode != 0 or not mem.stdout.strip():
        return None

    try:
        used_s, total_s, util_s = (c.strip() for c in mem.stdout.strip().splitlines()[0].split(","))
        used_mb, total_mb = int(used_s), int(total_s)
        util_pct = int(util_s)
    except (ValueError, IndexError):
        return None

    procs: list[dict] = []
    for line in apps.stdout.splitlines() if apps.returncode == 0 else []:
        parts = [c.strip() for c in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            pid, mem_mb = int(parts[0]), int(parts[2])
        except ValueError:
            continue  # e.g. used_memory reported as "[N/A]"
        procs.append({"pid": pid, "name": parts[1].split("/")[-1], "mem_mb": mem_mb})

    return {
        "used_mb": used_mb, "total_mb": total_mb,
        "free_mb": max(0, total_mb - used_mb), "util_pct": util_pct,
        "processes": procs,
    }


def gpu_contention_summary(activity: Optional[dict], own_pids=()) -> dict:
    """Decide whether the GPU is too busy to start a new run, from raw activity.

    Pure (no I/O) so it is unit-testable.  ``own_pids`` are this app's own running
    NAMD PIDs — excluded so the concurrent-job guard, not this one, speaks for
    them.  ``busy`` is True when any *external* compute process holds at least
    ``_GPU_BUSY_PROC_MB``.  Returns ``{available, busy, processes, used_mb,
    total_mb, free_mb, util_pct, message}``.
    """
    if not activity:
        return {"available": False, "busy": False, "processes": [], "message": ""}
    own = set(own_pids or ())
    heavy = [
        p for p in activity["processes"]
        if p["mem_mb"] >= _GPU_BUSY_PROC_MB and p["pid"] not in own
    ]
    busy = bool(heavy)
    if busy:
        who = ", ".join(f"{p['name']} ({p['mem_mb']:,} MB)" for p in heavy)
        message = (
            f"GPU {activity['used_mb']:,}/{activity['total_mb']:,} MB in use by another "
            f"process: {who}. Starting a second GPU run may run out of VRAM or slow both "
            f"to a crawl."
        )
    else:
        message = ""
    return {
        "available": True, "busy": busy, "processes": heavy,
        "used_mb": activity["used_mb"], "total_mb": activity["total_mb"],
        "free_mb": activity["free_mb"], "util_pct": activity["util_pct"],
        "message": message,
    }


def max_atoms_for_vram(vram_mb: float) -> int:
    """Largest system (atoms) expected to fit in *vram_mb* of GPU memory."""
    return int(vram_mb * _USABLE_FRACTION / _MB_PER_MATOM * 1e6)


def estimate_vram_mb(n_atoms: int) -> int:
    """Estimated peak VRAM (MB) for an *n_atoms* explicit-solvent NAMD run."""
    return int(round(n_atoms / 1e6 * _MB_PER_MATOM))


def required_vram_mb(n_atoms: int) -> int:
    """Total VRAM (MB) a card would need to fit *n_atoms* (incl. headroom)."""
    return int(round(estimate_vram_mb(n_atoms) / _USABLE_FRACTION))


# ══════════════════════════════════════════════════════════════════════════════
# §3  DOWNSIZE ESTIMATE
# ══════════════════════════════════════════════════════════════════════════════

def _grid_nearest_dna_dist(dna_xyz_nm, shell_max_nm: float, grid_nm: float = 0.6):
    """Return (distances, cell_volume_nm3) for a regular grid over the DNA + shell.

    Each grid point's nearest-DNA distance lets us count the hydration volume for
    any shell ≤ ``shell_max_nm`` by simple thresholding (computed once, reused).
    """
    import numpy as np  # noqa: PLC0415
    from scipy.spatial import cKDTree  # noqa: PLC0415

    P = np.asarray(dna_xyz_nm, dtype=float)
    lo = P.min(0) - shell_max_nm
    hi = P.max(0) + shell_max_nm
    axes = [np.arange(lo[i], hi[i] + grid_nm, grid_nm) for i in range(3)]
    gx, gy, gz = np.meshgrid(*axes, indexing="ij")
    grid = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])
    dist, _ = cKDTree(P).query(grid, k=1, workers=-1)
    return dist, grid_nm ** 3


def estimate_total_atoms(
    *,
    dna_xyz_nm,
    box_nm: tuple[float, float, float],
    full_water: int,
    dna_atoms: int,
    ion_atoms: int,
    shell_nm: float,
    _grid_cache: Optional[tuple] = None,
) -> int:
    """Estimate the solvated atom count if water is carved to *shell_nm*.

    Water fills the box uniformly, so the carved water count scales with the
    fraction of the box volume that lies within ``shell_nm`` of the DNA:

        carved_water ≈ full_water · shell_volume / box_volume

    ``shell_volume`` is measured on a coarse grid.  Ions are held fixed (≈1 % of
    atoms — negligible for a fit decision).
    """
    bx, by, bz = box_nm
    box_vol = bx * by * bz
    dist, cell_vol = _grid_cache if _grid_cache is not None else _grid_nearest_dna_dist(
        dna_xyz_nm, max(CANDIDATE_SHELLS_NM)
    )
    shell_vol = float((dist <= shell_nm).sum()) * cell_vol
    frac = min(1.0, shell_vol / box_vol) if box_vol > 0 else 1.0
    carved_water = int(round(full_water * frac))
    return dna_atoms + carved_water * 3 + ion_atoms


def recommend_downsize(
    *,
    dna_xyz_nm,
    box_nm: tuple[float, float, float],
    full_water: int,
    dna_atoms: int,
    ion_atoms: int,
    vram_mb: float,
) -> dict:
    """Recommend a water-shell thickness that fits *vram_mb*, or report infeasible.

    Picks the **largest** (least restrictive, most accurate) candidate shell whose
    estimated atom count fits; if none fit, reports the tightest shell's size and
    the VRAM a card would need.
    """
    max_atoms = max_atoms_for_vram(vram_mb)
    current_atoms = dna_atoms + full_water * 3 + ion_atoms
    grid = _grid_nearest_dna_dist(dna_xyz_nm, max(CANDIDATE_SHELLS_NM))

    estimates = []
    for shell in CANDIDATE_SHELLS_NM:
        est = estimate_total_atoms(
            dna_xyz_nm=dna_xyz_nm, box_nm=box_nm, full_water=full_water,
            dna_atoms=dna_atoms, ion_atoms=ion_atoms, shell_nm=shell,
            _grid_cache=grid,
        )
        estimates.append((shell, est))

    base = {
        "current_atoms": current_atoms,
        "current_vram_mb": estimate_vram_mb(current_atoms),
        "max_atoms": max_atoms,
        "vram_mb": int(vram_mb),
        "candidates": [{"shell_nm": s, "atoms": a} for s, a in estimates],
    }

    for shell, est in estimates:                      # largest shell first
        if est <= max_atoms:
            return {
                **base,
                "feasible": True,
                "recommended_shell_nm": shell,
                "estimated_atoms": est,
                "estimated_vram_mb": estimate_vram_mb(est),
            }

    tight_shell, tight_atoms = estimates[-1]          # smallest shell
    return {
        **base,
        "feasible": False,
        "recommended_shell_nm": None,
        "tightest_shell_nm": tight_shell,
        "tightest_atoms": tight_atoms,
        "required_vram_mb": required_vram_mb(tight_atoms),
    }


# ══════════════════════════════════════════════════════════════════════════════
# §4  PACKAGE PROFILE
# ══════════════════════════════════════════════════════════════════════════════

def _read_dna_atoms_from_pdb(pdb_path: Path) -> "list[tuple[float, float, float]]":
    """DNA heavy-atom (x, y, z) in nm — the leading ATOM records of a solvated PDB.

    Water/ions are HETATM and always follow the DNA ATOM block, so we stop at the
    first HETATM once DNA has been seen (avoids scanning millions of solvent lines).
    """
    pts: list[tuple[float, float, float]] = []
    with pdb_path.open() as fh:
        for line in fh:
            if line.startswith("ATOM"):
                try:
                    pts.append((
                        float(line[30:38]) / 10.0,
                        float(line[38:46]) / 10.0,
                        float(line[46:54]) / 10.0,
                    ))
                except ValueError:
                    pass
            elif line.startswith("HETATM") and pts:
                break
    return pts


def package_solvation_profile(package_dir: Path, name_stem: str) -> Optional[dict]:
    """Extract the inputs :func:`recommend_downsize` needs from a built package.

    Returns None if the package lacks the charge audit or PDB needed to estimate.
    """
    import json  # noqa: PLC0415

    audit_path = package_dir / "charge_audit.json"
    pdb_path = package_dir / f"{name_stem}.pdb"
    if not audit_path.exists() or not pdb_path.exists():
        return None
    try:
        ion = json.loads(audit_path.read_text()).get("ionization", {})
    except (OSError, ValueError):
        return None

    n_waters = int(ion.get("n_waters", 0))
    n_na = int(ion.get("n_na", 0))
    n_mg = int(ion.get("n_mg", 0))
    n_cl = int(ion.get("n_cl", 0))
    mgh = bool(ion.get("mg_hexahydrate", False))
    box = ion.get("box_nm")
    if not box or n_waters <= 0:
        return None
    ion_atoms = n_na + n_cl + n_mg * (19 if mgh else 1)

    dna_xyz = _read_dna_atoms_from_pdb(pdb_path)
    if not dna_xyz:
        return None

    return {
        "dna_xyz_nm": dna_xyz,
        "dna_atoms": len(dna_xyz),
        "box_nm": tuple(box),
        "full_water": n_waters,
        "ion_atoms": ion_atoms,
        "current_water_shell_nm": ion.get("water_shell_nm"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# §5  PRE-FLIGHT AUTO-SIZING  (proactive: pick settings before the run)
# ══════════════════════════════════════════════════════════════════════════════

def estimate_profile_from_design(design, *, padding_nm: float = 1.2,
                                 atomistic_model=None) -> Optional[dict]:
    """Estimate a solvation profile from the *dry* design — no GROMACS run.

    Builds the heavy-atom PDB, takes the bounding box + padding as the solvation
    box, and estimates the full-box water count from the effective bulk density.
    Good enough to decide, before any solvation, whether the system needs a carve.
    """
    import numpy as np  # noqa: PLC0415
    from backend.core.pdb_export import export_pdb  # noqa: PLC0415

    pdb = export_pdb(design, box_margin_nm=padding_nm, model=atomistic_model)
    dna: list[tuple[float, float, float]] = []
    n_p = 0
    for ln in pdb.splitlines():
        if not ln.startswith("ATOM"):
            continue
        try:
            dna.append((float(ln[30:38]) / 10.0, float(ln[38:46]) / 10.0,
                        float(ln[46:54]) / 10.0))
        except ValueError:
            continue
        if ln[12:16].strip() == "P":
            n_p += 1
    if not dna:
        return None

    P = np.asarray(dna, dtype=float)
    ext = P.max(0) - P.min(0)
    box_nm = tuple(float(e) + 2 * padding_nm for e in ext)
    box_vol = box_nm[0] * box_nm[1] * box_nm[2]
    return {
        "dna_xyz_nm": dna,
        "dna_atoms": len(dna),
        "box_nm": box_nm,
        "full_water": int(box_vol * _FULL_BOX_WATER_DENSITY_NM3),
        "ion_atoms": n_p,           # ≈ one neutralising Na⁺ per phosphate
        "current_water_shell_nm": None,
    }


def auto_water_shell(design, *, padding_nm: float = 1.2, devices: str = "0",
                     atomistic_model=None) -> dict:
    """Pre-flight: pick a water-shell (nm) that fits the GPU, or 0 for full box.

    Returns ``{shell_nm, note, fits, vram_mb}``.  ``shell_nm == 0`` means either no
    carve is needed (full box fits) or sizing was unavailable (no GPU read / no
    profile) — in both cases the caller keeps the user's setting.  A non-zero
    ``shell_nm`` comes with a human ``note`` explaining the automatic choice.
    """
    none = {"shell_nm": 0.0, "note": None, "fits": None, "vram_mb": None}
    vram_mb = detect_vram_mb(devices)
    if vram_mb is None:
        return none
    # Best-effort: a preflight estimate must never fail the job — on any error,
    # fall back to the full box (the prior behaviour).
    try:
        profile = estimate_profile_from_design(
            design, padding_nm=padding_nm, atomistic_model=atomistic_model)
        if profile is None:
            return {**none, "vram_mb": vram_mb}
        rec = recommend_downsize(
            dna_xyz_nm=profile["dna_xyz_nm"], box_nm=profile["box_nm"],
            full_water=profile["full_water"], dna_atoms=profile["dna_atoms"],
            ion_atoms=profile["ion_atoms"], vram_mb=vram_mb,
        )
    except Exception:
        return {**none, "vram_mb": vram_mb}
    gb = round(vram_mb / 1024)
    if rec["current_atoms"] <= rec["max_atoms"]:
        return {"shell_nm": 0.0, "note": None, "fits": True, "vram_mb": vram_mb}
    if rec.get("feasible"):
        s = rec["recommended_shell_nm"]
        note = (f"Auto-sized for {gb} GB GPU: full system ≈{rec['current_atoms']:,} "
                f"atoms won’t fit, so enabled a {round(s * 10)} Å water shell "
                f"(≈{rec['estimated_atoms']:,} atoms, NVT).")
        return {"shell_nm": s, "note": note, "fits": True, "vram_mb": vram_mb}
    s = rec["tightest_shell_nm"]
    note = (f"Warning: even a {round(s * 10)} Å shell (≈{rec['tightest_atoms']:,} atoms) "
            f"may exceed this {gb} GB GPU — running anyway; consider a larger GPU.")
    return {"shell_nm": s, "note": note, "fits": False, "vram_mb": vram_mb}
