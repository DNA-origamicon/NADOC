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
from dataclasses import dataclass
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
# A CUDA out-of-memory that is really a *host* (pinned CPU RAM) allocation failure,
# not device VRAM: cudaHostAlloc / cudaMallocHost pin page-locked host memory, and
# NAMD's bonded-CUDA path stages bond/angle/exclusion tuples through such buffers
# (reallocate_host_T → ComputeBondedCUDA::copyTupleDataSN). These abort with the
# same "out of memory" string but a water-shell carve won't fix them — the culprit
# is host RAM / pinnable-pool pressure (common on WSL2 and with large ENM restraint
# sets), so the remedy is to free host memory and resume, not to shrink the system.
_HOST_OOM_PAT = re.compile(
    r"cudaHostAlloc|cudaMallocHost|reallocate_host|allocate_host|copyTupleData",
    re.IGNORECASE,
)
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
FAILURE_HOST_OOM = "host_oom"
FAILURE_INSTABILITY = "instability"
FAILURE_GPU_ERROR = "gpu_error"
FAILURE_CELL_SHRINK = "cell_shrink"
# The user PINNED a production timestep the package cannot run (4 fs on a declash build,
# which has no HMR PSF).  Not detected from a log — it is a config conflict raised before
# any step is integrated.  It exists as a failure KIND rather than a request rejection so
# the run appears in the job list and the standard Fix popup can explain it, instead of
# the old behaviour: silently substituting 1 fs and producing a different trajectory.
FAILURE_TIMESTEP_PINNED = "timestep_pinned"
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
    a host-pinned-memory OOM (cudaHostAlloc/copyTupleData) is disambiguated from a
    device-VRAM OOM before either is returned; a RATTLE/margin blow-up is matched
    before the generic GPU-error pattern. The cell-shrink fatal has a unique string
    and does not overlap the others.
    """
    if _OOM_PAT.search(text):
        return FAILURE_HOST_OOM if _HOST_OOM_PAT.search(text) else FAILURE_VRAM_OOM
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


# ── Failure → UX description (drives the Relax decision gates) ─────────────────

@dataclass(frozen=True)
class FailureUX:
    """UX-layer description of a NAMD failure: what to tell the user, and how to act.

    ``severity`` picks the surface the Relax flow shows:
      ``"auto"``      NADOC handles it (auto-resume) — show an info note, no modal.
      ``"decision"``  a real trade-off — ask the user (a proceed/cancel modal).
      ``"hard_stop"`` a limit — the user must change something to proceed.

    ``retry_other_binary`` is True ONLY for the CUDA tile-list kernel bug
    (``gpu_error``), which a resident-capable NAMD build fixes — a host-pinned-memory
    limit or a device-VRAM OOM does not, so those stay False. ``degrade_target`` is the
    slower fallback to OFFER (never auto-take): ``"offload"`` (GPU, ~3× slower) or
    ``"cpu"``. ``message`` is jargon-free and safe to show; the raw NAMD cause line is
    kept in ``technical_reason`` for logs/tooltips only — never as the headline.
    """
    kind: str
    severity: str
    title: str
    message: str
    retry_other_binary: bool
    degrade_target: Optional[str]
    technical_reason: str


# kind → (severity, title, message, retry_other_binary, degrade_target). Copy is a
# sensible backend default; the frontend may enrich it (e.g. exact time estimates).
_FAILURE_UX: dict[str, dict] = {
    FAILURE_VRAM_OOM: dict(
        severity="hard_stop", retry_other_binary=False, degrade_target=None,
        title="Too large for this GPU",
        message="This structure needs more GPU memory than your card has. Reduce the "
                "design, or run it on a GPU with more memory."),
    FAILURE_HOST_OOM: dict(
        severity="decision", retry_other_binary=False, degrade_target="offload",
        title="Couldn't use the fastest GPU mode",
        message="Your system can't hold the extra memory the fastest GPU mode needs. "
                "The run can still finish in a slower GPU mode — same result, about "
                "3× longer."),
    FAILURE_GPU_ERROR: dict(
        severity="decision", retry_other_binary=True, degrade_target="offload",
        title="Couldn't use the fastest GPU mode",
        message="The fastest GPU mode didn't start on this structure. A newer NAMD build "
                "usually fixes this; otherwise the run can finish in a slower GPU mode "
                "— same result, about 3× longer."),
    FAILURE_INSTABILITY: dict(
        severity="auto", retry_other_binary=False, degrade_target=None,
        title="Restarting more gently",
        message="The start was too strained. NADOC is retrying with a gentler warm-up "
                "— no action needed."),
    FAILURE_CELL_SHRINK: dict(
        severity="auto", retry_other_binary=False, degrade_target=None,
        title="Continuing from the last checkpoint",
        message="The simulation box settled to a smaller size. NADOC is continuing from "
                "the last checkpoint — no action needed."),
    FAILURE_OTHER: dict(
        severity="decision", retry_other_binary=False, degrade_target=None,
        title="The run hit an unexpected error",
        message="The run stopped with an error NADOC doesn't recognize. See the run log "
                "for details."),
}


def describe_failure(text: str) -> FailureUX:
    """Classify a NAMD failure log and describe it for the Relax UX layer.

    Pairs :func:`classify_failure_log` with the presentation metadata the decision
    gates need (severity, jargon-free message, retry-other-binary, degrade target).
    The raw NAMD cause line is carried in ``technical_reason`` (logs/tooltips only).
    """
    kind = classify_failure_log(text)
    spec = _FAILURE_UX.get(kind, _FAILURE_UX[FAILURE_OTHER])
    return FailureUX(kind=kind, technical_reason=extract_error_line(text) or "", **spec)


def describe_failure_file(path: Path) -> FailureUX:
    """:func:`describe_failure` over a NAMD log *file* (tail only)."""
    return describe_failure(_read_log_tail(path))


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


# ── Empirical HOST-RAM model ──────────────────────────────────────────────────
# A NAMD explicit-solvent run also needs host (CPU) RAM: the full topology + patch
# metadata, and — the part that actually bit us — page-locked "pinned" staging
# buffers the GPU bonded kernel allocates via cudaHostAlloc (see FAILURE_HOST_OOM).
# This is a COARSE guard, deliberately conservative in the direction of NOT carving:
# it should only shrink a run on a genuinely small-RAM machine, never second-guess a
# box that has room (carving swaps the full periodic box for an NVT shell, a real
# accuracy cost). ~2.5 GB per million atoms is a safety-margined figure for the
# multicore-CUDA build under a dense elastic network; refine if a small-RAM machine
# is seen to OOM below this or to over-carve above it.
_HOST_MB_PER_MATOM = 2500.0
# Fraction of *currently-available* host RAM a run may claim — leaves generous room
# for the OS, the NADOC server, and a browser/live-viewer sharing the machine.
_HOST_USABLE_FRACTION = 0.6


def detect_host_ram_mb() -> Optional[int]:
    """Currently-available host RAM (MB) from /proc/meminfo, or None if unreadable.

    Uses ``MemAvailable`` (the kernel's estimate of what a new allocation can get
    without swapping) rather than ``MemTotal`` — a preflight cares about headroom
    *now*, not the installed size. Best-effort: any parse failure yields None so the
    caller degrades to "unknown / keep the user's setting".
    """
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024  # kB → MB
    except (OSError, ValueError, IndexError):
        return None
    return None


def max_atoms_for_host_ram(host_mb: float) -> int:
    """Largest system (atoms) expected to fit in *host_mb* of available host RAM."""
    return int(host_mb * _HOST_USABLE_FRACTION / _HOST_MB_PER_MATOM * 1e6)


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


def carve_fill_fraction(dna_xyz_nm, box_nm: tuple[float, float, float],
                        shell_nm: float) -> float:
    """Fraction of the periodic cell volume filled by a ``shell_nm`` water carve around
    the DNA (0..1). GPU-resident needs a well-filled cell — a *tight* box the structure
    fills runs resident, a *big* box with a concave water-shell carve leaves vacuum
    corners and dies at step 0 ("Low global CUDA exclusion count!"). This lets the
    conf builder tell those apart instead of blanket-disabling resident on any carve.
    A shell of 0 (no carve / full box) is fully filled → 1.0.
    """
    if not shell_nm or shell_nm <= 0:
        return 1.0
    bx, by, bz = box_nm
    box_vol = bx * by * bz
    if box_vol <= 0:
        return 1.0
    dist, cell_vol = _grid_nearest_dna_dist(dna_xyz_nm, shell_nm)
    shell_vol = float((dist <= shell_nm).sum()) * cell_vol
    return min(1.0, shell_vol / box_vol)


def recommend_downsize(
    *,
    dna_xyz_nm,
    box_nm: tuple[float, float, float],
    full_water: int,
    dna_atoms: int,
    ion_atoms: int,
    vram_mb: float,
    max_atoms: Optional[int] = None,
) -> dict:
    """Recommend a water-shell thickness that fits the atom budget, or report infeasible.

    Picks the **largest** (least restrictive, most accurate) candidate shell whose
    estimated atom count fits; if none fit, reports the tightest shell's size and
    the VRAM a card would need.

    ``max_atoms`` overrides the VRAM-derived budget — pass the tighter of the GPU and
    host-RAM caps so the recommendation also respects host memory. ``vram_mb`` is
    still reported for the message either way.
    """
    if max_atoms is None:
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

# One Relax click used to build the design's whole heavy-atom model THREE times — once
# for ⚡ Optimize, once for the disk forecast, once for the real prep — at ~26 s each on a
# 6-helix bundle.  The design cannot change between them (a mutation changes its
# fingerprint), so memoise on (fingerprint, padding, model identity).  Tiny cache: the
# profile holds an Nx3 coordinate array, and only the active design is ever asked for.
_PROFILE_CACHE: "dict[tuple, dict]" = {}
_PROFILE_CACHE_MAX = 2


def _profile_cache_key(design, padding_nm: float, atomistic_model) -> Optional[tuple]:
    """Cache key, or None when the design won't fingerprint (→ don't cache)."""
    try:
        from backend.core.oxdna_staleness import design_build_fingerprint  # noqa: PLC0415

        return (design_build_fingerprint(design), round(float(padding_nm), 4),
                id(atomistic_model) if atomistic_model is not None else None)
    except Exception:  # noqa: BLE001
        return None


def clear_profile_cache() -> None:
    """Drop the memoised solvation profiles (tests; and any explicit invalidation)."""
    _PROFILE_CACHE.clear()


def estimate_profile_from_design(design, *, padding_nm: float = 1.2,
                                 atomistic_model=None) -> Optional[dict]:
    """Estimate a solvation profile from the *dry* design — no GROMACS run.

    Builds the heavy-atom PDB, takes the bounding box + padding as the solvation
    box, and estimates the full-box water count from the effective bulk density.
    Good enough to decide, before any solvation, whether the system needs a carve.

    Memoised on the design's build fingerprint — see ``_PROFILE_CACHE``.  The result is
    treated as read-only by every caller (they only read its keys), so the cached dict
    is handed back directly.
    """
    import numpy as np  # noqa: PLC0415
    from backend.core.pdb_export import export_pdb  # noqa: PLC0415

    key = _profile_cache_key(design, padding_nm, atomistic_model)
    if key is not None and key in _PROFILE_CACHE:
        return _PROFILE_CACHE[key]

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
    profile = {
        "dna_xyz_nm": dna,
        "dna_atoms": len(dna),
        "box_nm": box_nm,
        "full_water": int(box_vol * _FULL_BOX_WATER_DENSITY_NM3),
        "ion_atoms": n_p,           # ≈ one neutralising Na⁺ per phosphate
        "current_water_shell_nm": None,
    }
    if key is not None:
        if len(_PROFILE_CACHE) >= _PROFILE_CACHE_MAX:
            _PROFILE_CACHE.pop(next(iter(_PROFILE_CACHE)))   # evict oldest
        _PROFILE_CACHE[key] = profile
    return profile


def auto_water_shell(design, *, padding_nm: float = 1.2, devices: str = "0",
                     atomistic_model=None) -> dict:
    """Pre-flight: pick a water-shell (nm) that fits the GPU, or 0 for full box.

    Returns ``{shell_nm, note, fits, vram_mb}``.  ``shell_nm == 0`` means either no
    carve is needed (full box fits) or sizing was unavailable (no GPU read / no
    profile) — in both cases the caller keeps the user's setting.  A non-zero
    ``shell_nm`` comes with a human ``note`` explaining the automatic choice.
    """
    none = {"shell_nm": 0.0, "note": None, "fits": None, "vram_mb": None}
    host_mb = detect_host_ram_mb()
    cpu = (devices or "").strip().lower() in ("cpu", "none")
    if cpu:
        # CPU (multicore) build has no VRAM ceiling — size the carve to host RAM
        # only.  The carve still helps: fewer atoms = faster CPU minimisation.
        if not host_mb:
            return none
        vram_mb = None
        effective_cap = max_atoms_for_host_ram(host_mb)
        bound = "host RAM"
    else:
        vram_mb = detect_vram_mb(devices)
        if vram_mb is None:
            return none
        # The run must fit BOTH the GPU and host RAM; size to the tighter cap.
        vram_cap = max_atoms_for_vram(vram_mb)
        host_cap = max_atoms_for_host_ram(host_mb) if host_mb else None
        effective_cap = min(vram_cap, host_cap) if host_cap is not None else vram_cap
        bound = "host RAM" if host_cap is not None and host_cap < vram_cap else "GPU"
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
            ion_atoms=profile["ion_atoms"],
            # No VRAM bound on CPU — pass a huge sentinel so only max_atoms (host) binds.
            vram_mb=vram_mb if vram_mb is not None else 10**9,
            max_atoms=effective_cap,
        )
    except Exception:
        return {**none, "vram_mb": vram_mb}
    limit = (f"{round(host_mb / 1024)} GB free host RAM" if bound == "host RAM"
             else f"{round(vram_mb / 1024)} GB GPU")
    if rec["current_atoms"] <= rec["max_atoms"]:
        return {"shell_nm": 0.0, "note": None, "fits": True, "vram_mb": vram_mb}
    if rec.get("feasible"):
        s = rec["recommended_shell_nm"]
        note = (f"Auto-sized for {limit}: full system ≈{rec['current_atoms']:,} "
                f"atoms won’t fit, so enabled a {round(s * 10)} Å water shell "
                f"(≈{rec['estimated_atoms']:,} atoms, NVT).")
        return {"shell_nm": s, "note": note, "fits": True, "vram_mb": vram_mb}
    s = rec["tightest_shell_nm"]
    note = (f"Warning: even a {round(s * 10)} Å shell (≈{rec['tightest_atoms']:,} atoms) "
            f"may exceed this {limit} — running anyway; consider a larger GPU or more RAM.")
    return {"shell_nm": s, "note": note, "fits": False, "vram_mb": vram_mb}


# ── Pre-flight size gate (Gate A: A1 auto-notice / A2 tight-shell / A3 too-large) ──

_SAFE_SHELL_NM = 1.5   # a ≥15 Å water shell is "comfortable" (A1); tighter is a trade-off (A2)


def classify_vram_fit(rec: Optional[dict]) -> str:
    """Pre-flight size-gate tier from a :func:`recommend_downsize` advice:
      ``"ok"`` full box fits (or data missing — never gate on the unknown);
      ``"a1"`` a comfortable thinner shell (≥15 Å) fits → auto-apply + a friendly notice;
      ``"a2"`` only a TIGHT shell (<15 Å) fits → an accuracy trade-off, so ask;
      ``"a3"`` won't fit even at the tightest shell → hard stop.
    """
    if not rec:
        return "ok"
    max_atoms = rec.get("max_atoms") or 0
    if max_atoms <= 0 or rec.get("current_atoms", 0) <= max_atoms:
        return "ok"
    if not rec.get("feasible"):
        return "a3"
    return "a1" if (rec.get("recommended_shell_nm") or 0) >= _SAFE_SHELL_NM else "a2"


def preflight_vram_advice(design, *, padding_nm: float = 1.2, devices: str = "0",
                          atomistic_model=None) -> dict:
    """Pre-flight size verdict for the Relax launch gate — computed from the DRY design
    (no build). Returns the :func:`recommend_downsize` advice enriched with ``tier``
    (ok/a1/a2/a3), ``bound`` ("GPU"/"host RAM") and ``host_mb``; or ``{"skipped": True,
    "tier": "ok"}`` whenever sizing can't run (no GPU read / no profile / any error) so
    the launch proceeds unchanged. Shares auto_water_shell's detect chain but surfaces
    the full advice for the UI instead of only the chosen shell.
    """
    skipped = {"skipped": True, "tier": "ok"}
    host_mb = detect_host_ram_mb()
    cpu = (devices or "").strip().lower() in ("cpu", "none")
    if cpu:
        if not host_mb:
            return skipped
        vram_mb, effective_cap, bound = None, max_atoms_for_host_ram(host_mb), "host RAM"
    else:
        vram_mb = detect_vram_mb(devices)
        if vram_mb is None:
            return skipped
        vram_cap = max_atoms_for_vram(vram_mb)
        host_cap = max_atoms_for_host_ram(host_mb) if host_mb else None
        effective_cap = min(vram_cap, host_cap) if host_cap is not None else vram_cap
        bound = "host RAM" if host_cap is not None and host_cap < vram_cap else "GPU"
    try:
        profile = estimate_profile_from_design(
            design, padding_nm=padding_nm, atomistic_model=atomistic_model)
        if profile is None:
            return skipped
        rec = recommend_downsize(
            dna_xyz_nm=profile["dna_xyz_nm"], box_nm=profile["box_nm"],
            full_water=profile["full_water"], dna_atoms=profile["dna_atoms"],
            ion_atoms=profile["ion_atoms"],
            vram_mb=vram_mb if vram_mb is not None else 10**9,
            max_atoms=effective_cap,
        )
    except Exception:  # noqa: BLE001 — a preflight must never block a launch
        return skipped
    return {**rec, "skipped": False, "tier": classify_vram_fit(rec),
            "bound": bound, "host_mb": host_mb}
