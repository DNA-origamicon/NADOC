"""GPU-VRAM failure detection and full-system sizing for NAMD jobs.

A large explicit-solvent origami can exceed the GPU's memory and abort with a
CUDA ``out of memory`` error at startup.  This module:

  1. recognises that failure in a NAMD log (:func:`log_indicates_oom`),
  2. reads the GPU's total VRAM (:func:`detect_vram_mb`),
  3. estimates whether the complete explicitly solvated system fits.

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
_GPU_ERR_PAT = re.compile(
    r"buildTileLists|cudaStreamSynchronize|CUDA error", re.IGNORECASE
)
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
    re.compile(
        r"^.*DUE TO (?:TIME LIMIT|NODE FAILURE|PREEMPTION|JOB REQUEUE).*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"^.*(?:oom-kill|out of memory|outofmemory).*$", re.IGNORECASE | re.MULTILINE
    ),
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
        severity="hard_stop",
        retry_other_binary=False,
        degrade_target=None,
        title="Too large for this GPU",
        message="This structure needs more GPU memory than your card has. Reduce the "
        "design, or run it on a GPU with more memory.",
    ),
    FAILURE_HOST_OOM: dict(
        severity="decision",
        retry_other_binary=False,
        degrade_target="offload",
        title="Couldn't use the fastest GPU mode",
        message="Your system can't hold the extra memory the fastest GPU mode needs. "
        "The run can still finish in a slower GPU mode — same result, about "
        "3× longer.",
    ),
    FAILURE_GPU_ERROR: dict(
        severity="decision",
        retry_other_binary=True,
        degrade_target="offload",
        title="Couldn't use the fastest GPU mode",
        message="The fastest GPU mode didn't start on this structure. A newer NAMD build "
        "usually fixes this; otherwise the run can finish in a slower GPU mode "
        "— same result, about 3× longer.",
    ),
    FAILURE_INSTABILITY: dict(
        severity="auto",
        retry_other_binary=False,
        degrade_target=None,
        title="Restarting more gently",
        message="The start was too strained. NADOC is retrying with a gentler warm-up "
        "— no action needed.",
    ),
    FAILURE_CELL_SHRINK: dict(
        severity="auto",
        retry_other_binary=False,
        degrade_target=None,
        title="Continuing from the last checkpoint",
        message="The simulation box settled to a smaller size. NADOC is continuing from "
        "the last checkpoint — no action needed.",
    ),
    FAILURE_OTHER: dict(
        severity="decision",
        retry_other_binary=False,
        degrade_target=None,
        title="The run hit an unexpected error",
        message="The run stopped with an error NADOC doesn't recognize. See the run log "
        "for details.",
    ),
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
            [
                exe,
                f"--id={dev}",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
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
            [
                exe,
                f"--id={dev}",
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        apps = subprocess.run(
            [
                exe,
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if mem.returncode != 0 or not mem.stdout.strip():
        return None

    try:
        used_s, total_s, util_s = (
            c.strip() for c in mem.stdout.strip().splitlines()[0].split(",")
        )
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
        "used_mb": used_mb,
        "total_mb": total_mb,
        "free_mb": max(0, total_mb - used_mb),
        "util_pct": util_pct,
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
        p
        for p in activity["processes"]
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
        "available": True,
        "busy": busy,
        "processes": heavy,
        "used_mb": activity["used_mb"],
        "total_mb": activity["total_mb"],
        "free_mb": activity["free_mb"],
        "util_pct": activity["util_pct"],
        "message": message,
    }


def max_atoms_for_vram(vram_mb: float) -> int:
    """Largest system (atoms) expected to fit in *vram_mb* of GPU memory."""
    return int(vram_mb * _USABLE_FRACTION / _MB_PER_MATOM * 1e6)


# ── Empirical HOST-RAM model ──────────────────────────────────────────────────
# A NAMD explicit-solvent run also needs host (CPU) RAM: the full topology + patch
# metadata, and — the part that actually bit us — page-locked "pinned" staging
# buffers the GPU bonded kernel allocates via cudaHostAlloc (see FAILURE_HOST_OOM).
# This is a coarse, safety-margined figure for the multicore-CUDA build under a dense
# elastic network. It is used only to decide whether the complete system fits.
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
# §3  PACKAGE PROFILE
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
                    pts.append(
                        (
                            float(line[30:38]) / 10.0,
                            float(line[38:46]) / 10.0,
                            float(line[46:54]) / 10.0,
                        )
                    )
                except ValueError:
                    pass
            elif line.startswith("HETATM") and pts:
                break
    return pts


def package_solvation_profile(package_dir: Path, name_stem: str) -> Optional[dict]:
    """Extract the atom-count inputs from a built explicit-solvent package."""
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
    from backend.core.namd_solvate import MGH_ATOMS  # noqa: PLC0415

    ion_atoms = n_na + n_cl + n_mg * (MGH_ATOMS if mgh else 1)

    dna_xyz = _read_dna_atoms_from_pdb(pdb_path)
    if not dna_xyz:
        return None

    return {
        "dna_xyz_nm": dna_xyz,
        "dna_atoms": len(dna_xyz),
        "box_nm": tuple(box),
        "full_water": n_waters,
        "ion_atoms": ion_atoms,
    }


# ══════════════════════════════════════════════════════════════════════════════
# §4  PRE-FLIGHT FULL-SYSTEM SIZING
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

        return (
            design_build_fingerprint(design),
            round(float(padding_nm), 4),
            id(atomistic_model) if atomistic_model is not None else None,
        )
    except Exception:  # noqa: BLE001
        return None


def clear_profile_cache() -> None:
    """Drop the memoised solvation profiles (tests; and any explicit invalidation)."""
    _PROFILE_CACHE.clear()


def estimate_atoms_from_design_geometry(design, *, padding_nm: float = 1.2) -> Optional[int]:
    """Fast, conservative solvated-atom estimate for interactive previews.

    Unlike :func:`estimate_profile_from_design`, this does not build the all-atom PDB.  That
    build is appropriate for the launch gate, where its coordinates are reused, but can take
    minutes for a large routed design and used to leave the Job Wizard saying ``checking…``
    for that entire time.  A preview only needs the atom-count scale used for price and VRAM
    ranking, so nucleotide count plus the helix-axis envelope is the honest cheap answer.

    The 1.2 nm radial allowance encloses the DNA atoms around each helix axis.  Terminal
    phosphates are omitted one per strand, matching the topology convention used by the exact
    estimator.  ``estimate_box_atoms`` then applies the same water-density, DNA-displacement,
    and hydrated-magnesium accounting as the production box sizer.
    """
    design = design.without_reference_geometry()
    import numpy as np  # noqa: PLC0415

    from backend.core.namd_solvate import estimate_box_atoms  # noqa: PLC0415
    from backend.core.sequences import strand_nucleotide_count  # noqa: PLC0415

    helices = list(getattr(design, "helices", None) or [])
    strands = list(getattr(design, "strands", None) or [])
    if not helices or not strands:
        return None

    try:
        n_nt = sum(strand_nucleotide_count(s, design) for s in strands)
        if n_nt <= 0:
            return None
        endpoints = np.asarray(
            [
                p.to_array()
                for helix in helices
                for p in (helix.axis_start, helix.axis_end)
            ],
            dtype=float,
        )
        if endpoints.ndim != 2 or endpoints.shape[1] != 3 or not np.isfinite(endpoints).all():
            return None
    except (AttributeError, TypeError, ValueError):
        return None

    # DNA residues average about 32 atoms including hydrogens. Rounding upward keeps the
    # preview on the safe side across base composition and 5'/3' terminal variants.
    n_dna_atoms = int(n_nt * 32)
    n_phosphates = max(0, n_nt - len(strands))
    dna_radius_nm = 1.2
    extent = endpoints.max(axis=0) - endpoints.min(axis=0)
    box_nm = tuple(float(x) + 2.0 * (dna_radius_nm + padding_nm) for x in extent)
    return estimate_box_atoms(box_nm, n_dna_atoms, n_phosphates)


def estimate_profile_from_design(
    design,
    *,
    padding_nm: float = 1.2,
    atomistic_model=None,
    nacl_mM: float = 0.0,
    mgcl2_mM: float = 12.5,
) -> Optional[dict]:
    """Estimate a solvation profile from the *dry* design — no GROMACS run.

    Builds the heavy-atom PDB, takes the bounding box + padding as the solvation
    box, and estimates the full-box water count from the effective bulk density.
    Good enough to decide, before solvation, whether the complete system fits.

    ``nacl_mM`` / ``mgcl2_mM`` default to the screening recipe the panel sends.  They
    matter because the ion census is no longer one atom per phosphate: under the
    Aksimentiev recipe the backbone is neutralised by Mg(H₂O)₆²⁺ at **19 atoms per
    cluster**, each of which also displaces six waters.  ``ion_atoms`` used to be
    ``n_p`` on the assumption of one neutralising Na⁺ per phosphate — a ~9.5x
    under-count of the ion atoms and a double-count of the displaced water, in a
    number Gate A sizes the whole box from.

    ``full_water`` is the count **after** ion displacement, so the consumer's
    ``dna_atoms + full_water * 3 + ion_atoms`` is a true total (and agrees with
    :func:`package_solvation_profile`, which reads post-placement counts).

    Memoised on the design's build fingerprint — see ``_PROFILE_CACHE``.  The result is
    treated as read-only by every caller (they only read its keys), so the cached dict
    is handed back directly.
    """
    design = design.without_reference_geometry()
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
            dna.append(
                (
                    float(ln[30:38]) / 10.0,
                    float(ln[38:46]) / 10.0,
                    float(ln[46:54]) / 10.0,
                )
            )
        except ValueError:
            continue
        if ln[12:16].strip() == "P":
            n_p += 1
    if not dna:
        return None

    from backend.core.namd_solvate import (  # noqa: PLC0415
        MGH_ATOMS,
        MGH_WATERS_CONSUMED,
        ion_counts,
    )

    P = np.asarray(dna, dtype=float)
    ext = P.max(0) - P.min(0)
    box_nm = tuple(float(e) + 2 * padding_nm for e in ext)
    box_vol = box_nm[0] * box_nm[1] * box_nm[2]

    water_before = int(box_vol * _FULL_BOX_WATER_DENSITY_NM3)
    ions = ion_counts(
        water_before,
        -float(n_p),
        nacl_mM=nacl_mM,
        mgcl2_mM=mgcl2_mM,
        box_nm=box_nm,
        mg_hexahydrate=True,
    )
    # Each MGH cluster is 19 atoms and vacates 6 waters; each monatomic ion takes
    # one water site.
    water_displaced = (ions.n_mg * MGH_WATERS_CONSUMED) + ions.n_na + ions.n_cl
    ion_atoms = ions.n_mg * MGH_ATOMS + ions.n_na + ions.n_cl

    profile = {
        "dna_xyz_nm": dna,
        "dna_atoms": len(dna),
        "box_nm": box_nm,
        "full_water": max(0, water_before - water_displaced),
        "ion_atoms": ion_atoms,
        "n_phosphates": n_p,
        "counterion": ions.counterion,
    }
    if key is not None:
        if len(_PROFILE_CACHE) >= _PROFILE_CACHE_MAX:
            _PROFILE_CACHE.pop(next(iter(_PROFILE_CACHE)))  # evict oldest
        _PROFILE_CACHE[key] = profile
    return profile


# ── Pre-flight size gate ──


def classify_vram_fit(rec: Optional[dict]) -> str:
    """Return ``ok`` when the full solvent box fits, otherwise a hard-stop tier."""
    if not rec:
        return "ok"
    max_atoms = rec.get("max_atoms") or 0
    if max_atoms <= 0 or rec.get("current_atoms", 0) <= max_atoms:
        return "ok"
    return "a3"


def preflight_vram_advice(
    design, *, padding_nm: float = 1.2, devices: str = "0", atomistic_model=None
) -> dict:
    """Pre-flight full-solvent size verdict computed from the dry design.

    Returns sizing advice enriched with ``tier`` (``ok`` or ``a3``), ``bound``
    ("GPU"/"host RAM") and ``host_mb``; or ``{"skipped": True,
    "tier": "ok"}`` whenever sizing can't run (no GPU read / no profile / any error) so
    the launch proceeds unchanged.
    """
    skipped = {"skipped": True, "tier": "ok"}
    host_mb = detect_host_ram_mb()
    cpu = (devices or "").strip().lower() in ("cpu", "none")
    if cpu:
        if not host_mb:
            return skipped
        vram_mb, effective_cap, bound = (
            None,
            max_atoms_for_host_ram(host_mb),
            "host RAM",
        )
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
            design, padding_nm=padding_nm, atomistic_model=atomistic_model
        )
        if profile is None:
            return skipped
        current_atoms = (
            profile["dna_atoms"] + profile["full_water"] * 3 + profile["ion_atoms"]
        )
        rec = {
            "current_atoms": current_atoms,
            "current_vram_mb": estimate_vram_mb(current_atoms),
            "required_vram_mb": required_vram_mb(current_atoms),
            "max_atoms": effective_cap,
            "vram_mb": int(vram_mb) if vram_mb is not None else None,
        }
    except Exception:  # noqa: BLE001 — a preflight must never block a launch
        return skipped
    tier = classify_vram_fit(rec)
    return {
        **rec,
        "skipped": False,
        "tier": tier,
        "bound": bound,
        "host_mb": host_mb,
    }
