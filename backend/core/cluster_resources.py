"""Auto-resource decision tree for remote MD submission (Alpine/SLURM).

The *offline* half of Phase 2 (see ``memory/project_alpine_cluster_submission.md``).
From a prepared job's sizing (total atoms, total simulated ns, and — when we have
it — a measured ns/day) recommend a partition + walltime + memory + QoS, and
estimate queue time and SU cost.  Everything here is pure and offline: no network,
no scheduler, no file writes.  It only *reads* a manifest / metrics file when the
convenience extractors are used.

Design decisions (from the plan):
- **GPU by default** — Alpine ``aa100`` (A100), one GPU, NAMD3 GPU-resident.  CPU
  ``acpu`` only when a system is too large for a single GPU.
- ``walltime = total_ns / expected_ns_per_day * safety_factor`` (in days → hours),
  clamped to the QoS ceiling; auto-bump ``normal``→``long`` rather than truncate.
- ``expected_ns_per_day`` uses a *measured* value when available (Phase 5 learns
  these); otherwise a size-based guess that is deliberately conservative.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from backend.core.cluster_config import ClusterProfile, Partition

# ── Tunables ──────────────────────────────────────────────────────────────────

# NAMD3 GPU-resident throughput scales ~ 1/atoms: ns/day ≈ C / atoms × speed factor.
#
# C was 2.9e6, a projection ("~180k atoms → >16 ns/day on an A100") never checked
# against a real run.  It is now anchored on a MEASURED production run: 2hb_1-0xT
# (62,673 atoms, 4 fs, with DCD + ENM restraints) sustained 30.8 ns/day on an
# a100_3g.20gb MIG slice (SLURM 30954752, 2026-08-07).  A 3g.20gb slice is ~3/7 of
# an A100, so a whole card is ~70 ns/day → C ≈ 70 × 62_673 ≈ 4.5e6.
#
# CAVEAT, deliberately conservative: this is ONE production point, and the whole-card
# scaling from a MIG slice is an estimate.  Bare-hardware BENCHMARKS on the same
# design run far faster still (644 ns/day for this system on an H200 with no DCD and
# no ENM — see project_alpine_cluster_submission.md), but benchmark conditions are an
# upper bound and using them here would under-request walltime and time jobs out.
# cluster_throughput.py supersedes this with real per-partition measurements as they
# accumulate; C only has to be right enough for a first run.
_GPU_NSDAY_ATOM_CONSTANT = 4.5e6

# NAMD3 GPU-resident throughput relative to an A100, per partition.  The constant
# above is A100-anchored, so every other GPU needs a multiplier.  This is load-
# bearing beyond cost display: walltime is derived from throughput, and an H200 job
# that requests 2.5x the walltime it needs gets WORSE queue priority for no reason.
# First-run guesses only — cluster_throughput.py is keyed cluster:partition:bucket,
# so real measured ns/day per partition supersedes these as soon as one run lands.
_GPU_SPEED_FACTOR = {
    "aa100": 1.0,           # the anchor
    "ah200": 2.5,           # H200: ~2-3x A100 on NAMD3 GPU-resident
    # MEASURED equal to the H200, not 1.6.  Head-to-head under identical settings
    # (2026-08-07): 2hb 650.0 vs 644.4 ns/day, 24hb 41.9 vs 38.2, VoltronCore 0.0761
    # vs 0.0753 s/step — Blackwell within ~10% either way across three system sizes.
    # It also bills LESS (242 vs 334 SU/GPU-h), so it is the SU-efficient choice.
    "artxpro6000": 2.5,
    # MEASURED 2026-08-07, not 0.75.  The old guess reasoned from fp64, which is
    # irrelevant to NAMD3 GPU-resident (single precision throughout).
    #
    # al40/ah200 measured at three sizes -- the ratio degrades MONOTONICALLY as the
    # system grows, which is a bandwidth story: L40 GDDR6 (~0.9 TB/s) vs H200 HBM3e
    # (~4.8 TB/s).  Small systems are latency-bound and hide it; large ones are
    # bandwidth-bound and expose it.
    #     2hb   63k atoms : 481.6 / 644.4 ns/day = 0.75
    #     24hb            :  23.0 /  38.2        = 0.60
    #     VoltronCore     :   0.6 /   1.1        = 0.55   <- production scale
    # Anchored on VoltronCore, the real production case: 0.55 * 2.5 = ~1.4.
    # A single scalar is therefore LOSSY for al40 -- it over-promises on small
    # systems.  If that starts to matter, make the factor size-dependent rather
    # than re-tuning this number.
    #
    # Also confirms the sm_90 binary JITs onto Ada sm_89 -- no separate al40 build.
    "al40": 1.4,
    "ami100": 0.5,          # AMD MI100 via HIP, historically the slowest here
    "atesting_a100": 1.0,
}

# Above this atom count a single A100 is no longer the obvious choice; fall back
# to a large CPU allocation.  A100 (80 GB) comfortably handles millions of atoms,
# so this ceiling is high on purpose — CPU is the exception, not the rule.
_GPU_ATOM_CEILING = 3_000_000

# Per-partition override of the ceiling above, for GPUs with much more VRAM than
# the 80 GB A100 the default was set against (H200 = 141 GB).
_GPU_ATOM_CEILING_BY_PARTITION = {
    "ah200": 6_000_000,
    "artxpro6000": 4_000_000,
}

_DEFAULT_SAFETY_FACTOR = 1.5

# GPU-resident NAMD needs only a handful of CPU cores (PME/patch work); more do
# not help and cost SU.  CPU fallback wants many.
_GPU_CORES = 8
_CPU_CORES = 32

# Per-partition queue-time fallback (minutes) for when there is NO live session.
# These are the 30-day MEDIAN waits measured on Alpine 2026-08-06 via `sacct -a`,
# not invented numbers — the previous guesses had aa100 at 240 min when its real
# median was 1425 and `sbatch --test-only` for a long job answered 13 DAYS.
# `GET /cluster/availability` supersedes all of this whenever a session is live.
_QUEUE_GUESS_MIN = {
    # aa100 is effectively UNSCHEDULABLE for a normal submission: 621 pending vs 28
    # running (2026-08-07), only 1 of those blocked on hardware — the rest are behind
    # fair-share, so backfill cannot help even a 15-minute job.  `squeue --start`
    # returns N/A: SLURM itself declines to predict a start.  The number below is a
    # placeholder that says "do not plan around this", not a real estimate.
    "aa100": 10080,        # 7 days
    "al40": 428,           # 638 samples
    "ami100": 1,           # 650 samples, median 0.5 min — unpopular, so wide open
    "ah200": 1,            # 97 samples — new, and the fastest card here
    "artxpro6000": 1,      # 58 samples; whole cards contended, MIG slices free
    "atesting_a100": 15,
    "acpu": 60,            # not measured (GPU-only probe); pre-2026 amilan figure
    "amem": 120,           # not measured
}


def gpu_speed_factor(partition: str | None) -> float:
    """Throughput of ``partition``'s GPU relative to an A100 (1.0 = A100)."""
    return _GPU_SPEED_FACTOR.get(partition or "", 1.0)


def gpu_atom_ceiling(partition: str | None) -> int:
    """Atom count above which ``partition``'s GPU stops being the obvious choice."""
    return _GPU_ATOM_CEILING_BY_PARTITION.get(partition or "", _GPU_ATOM_CEILING)


def _gpu_nsday_guess(n_atoms: int, partition: str | None = None) -> float:
    """Conservative first-run GPU throughput guess (ns/day) for ``n_atoms``.

    Scaled by the partition's GPU speed relative to the A100 the constant is
    anchored to; ``None`` (or an unknown partition) means no scaling.
    """
    n = max(1, int(n_atoms))
    return _GPU_NSDAY_ATOM_CONSTANT / n * gpu_speed_factor(partition)


def _mem_gb_for_atoms(n_atoms: int) -> int:
    """Memory request (GB) from atom count, with headroom.

    NAMD is memory-light (~KBs/atom); ~4 GB per 50k atoms plus a 4 GB floor is
    generous.  Rounded up to an integer GB.
    """
    return max(4, math.ceil(n_atoms / 50_000 * 4) + 4)


def _format_walltime(hours: float) -> str:
    """Format a positive number of hours as SLURM ``HH:MM:SS``."""
    total_seconds = max(60, int(math.ceil(hours * 3600)))
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def estimate_cost_su(
    cores: int,
    gpus: int,
    hours: float,
    profile: ClusterProfile,
    partition: Partition | None = None,
) -> float:
    """SU cost = cores·hours·su_per_core_hour + gpus·hours·su_per_gpu_hour.

    ``partition`` (optional) supplies a per-partition GPU rate — Alpine's ah200 /
    artxpro6000 are billed well above the A100 rate the profile-wide value carries,
    so omitting it under-quotes those jobs several-fold.
    """
    gpu_rate = profile.su_per_gpu_hour
    if partition is not None and partition.su_per_gpu_hour:
        gpu_rate = partition.su_per_gpu_hour
    return cores * hours * profile.su_per_core_hour + gpus * hours * gpu_rate


def estimate_queue_time_min(partition: str) -> int:
    """Rough expected queue wait (minutes) for a partition — a guess, not a SLA."""
    return _QUEUE_GUESS_MIN.get(partition, 60)


def recommend(
    profile: ClusterProfile,
    *,
    n_atoms: int,
    total_ns: float,
    measured_ns_per_day: float | None = None,
    safety_factor: float = _DEFAULT_SAFETY_FACTOR,
    partition: str | None = None,
) -> dict:
    """Recommend SLURM resources for a prepared job.

    Args:
        profile:  the target cluster (partition/QoS/billing come from here).
        n_atoms:  total atoms of the solvated system (PSF ``!NATOM`` / manifest).
        total_ns: total simulated nanoseconds the job will run (relax + prod).
        measured_ns_per_day: a real throughput if known (else a size-based guess).
        safety_factor: multiply the walltime estimate for headroom.
        partition: force a specific partition (e.g. ``acpu`` for a fast-queue
            validation run).  Everything dependent — kind, gpus, cores, gres_type,
            QoS, throughput class, cost — is re-derived from it so the request stays
            self-consistent.  ``None`` = auto-pick (GPU by default).  Raises
            ``ValueError`` if the named partition is not in the profile.

    Returns a dict: ``partition, kind, gpus, cores, mem_gb, walltime, walltime_h,
    qos, expected_ns_per_day, measured, est_queue_min, est_cost_su,
    safety_factor, notes``.
    """
    notes: list[str] = []
    n_atoms = max(1, int(n_atoms))
    total_ns = max(0.0, float(total_ns))

    if partition is not None:
        # User forced a partition (e.g. acpu for a quick, fast-queueing CPU
        # validation run).  Derive the rest from its kind so we never pair, say, a
        # CPU partition with a GPU QoS + GRES.
        part = profile.partition(partition)
        if part is None:
            raise ValueError(
                f"partition {partition!r} is not in profile {profile.name!r}"
            )
        partition_name = part.name
        use_gpu = part.kind == "gpu"
        gpus = 1 if use_gpu else 0
        cores = _GPU_CORES if use_gpu else min(_CPU_CORES, part.max_cores)
        notes.append(f"Partition manually set to {partition_name} ({part.kind}).")
    else:
        atom_ceiling = gpu_atom_ceiling(profile.default_partition)
        use_gpu = n_atoms <= atom_ceiling and profile.partition(profile.default_partition) is not None
        if not use_gpu:
            notes.append(
                f"{n_atoms:,} atoms exceeds the single-GPU ceiling "
                f"({atom_ceiling:,}); using a CPU partition."
            )
        if use_gpu:
            partition_name = profile.default_partition
            gpus = 1
            cores = _GPU_CORES
        else:
            # Prefer the general CPU partition (`acpu`; `amilan` pre-2026) for the fallback.
            cpu = (
                profile.partition("acpu")
                or profile.partition("amilan")
                or next((p for p in profile.partitions if p.kind == "cpu"), None)
            )
            partition_name = cpu.name if cpu else profile.default_partition
            gpus = 0
            cores = min(_CPU_CORES, cpu.max_cores if cpu else _CPU_CORES)
        part = profile.partition(partition_name)

    kind = part.kind if part else ("gpu" if use_gpu else "cpu")

    # Throughput → walltime.
    if measured_ns_per_day and measured_ns_per_day > 0:
        expected = float(measured_ns_per_day)
        notes.append(f"Using measured throughput {expected:.1f} ns/day.")
    else:
        if use_gpu:
            expected = _gpu_nsday_guess(n_atoms, partition_name)
            factor = gpu_speed_factor(partition_name)
            scaled = "" if factor == 1.0 else f" x{factor:g} for {partition_name}"
        else:
            expected = _gpu_nsday_guess(n_atoms) * 0.15
            scaled = ""
        notes.append(
            f"No measured throughput yet — guessing {expected:.1f} ns/day from system size"
            f"{scaled} (first run per size is a guess by design)."
        )

    raw_days = total_ns / expected if expected > 0 else 0.0
    walltime_h = raw_days * 24.0 * safety_factor

    # QoS selection + clamp to ceiling.  Names are partition-KIND aware: Alpine's
    # GPU partitions require the gpu-* QoS names (SLURM rejects the plain ones on
    # aa100), CPU partitions use the plain names.
    normal = profile.qos_for(kind, "normal")
    long_q = profile.qos_for(kind, "long")
    normal_name = normal.name if normal else ("gpu-normal" if kind == "gpu" else "normal")
    long_name = long_q.name if long_q else ("gpu-long" if kind == "gpu" else "long")
    normal_ceil = normal.max_walltime_h if normal else 24
    long_ceil = long_q.max_walltime_h if long_q else 168

    if walltime_h <= normal_ceil:
        qos = normal_name
    elif long_q is not None:
        qos = long_name
        notes.append(
            f"Estimated walltime {walltime_h:.1f} h exceeds the {normal_ceil} h "
            f"'{normal_name}' ceiling — bumped to '{long_name}'."
        )
    else:
        qos = normal_name

    ceiling = long_ceil if qos == long_name else normal_ceil
    if walltime_h > ceiling:
        notes.append(
            f"Estimated walltime {walltime_h:.1f} h exceeds the {qos} ceiling "
            f"{ceiling} h — clamped; the run may need auto-resubmit from a checkpoint."
        )
        walltime_h = float(ceiling)
    # A minimum so a tiny run still requests a sane block.
    walltime_h = max(walltime_h, 0.5)

    mem_gb = _mem_gb_for_atoms(n_atoms)
    if part and part.mem_per_core_gb:
        mem_ceiling = int(part.mem_per_core_gb * cores)
        if mem_gb > mem_ceiling:
            mem_gb = mem_ceiling
            notes.append(
                f"Memory clamped to {mem_gb} GB (partition ceiling {part.mem_per_core_gb} GB/core × {cores})."
            )

    est_cost = estimate_cost_su(cores, gpus, walltime_h, profile, part)
    est_queue = estimate_queue_time_min(partition_name)

    return {
        "partition": partition_name,
        "kind": kind,
        "gpus": gpus,
        "gres_type": (part.gres_type if part else "") if gpus else "",
        "cores": cores,
        "mem_gb": mem_gb,
        "walltime": _format_walltime(walltime_h),
        "walltime_h": round(walltime_h, 3),
        "qos": qos,
        "expected_ns_per_day": round(expected, 3),
        "measured": bool(measured_ns_per_day and measured_ns_per_day > 0),
        "est_queue_min": est_queue,
        "est_cost_su": round(est_cost, 1),
        "safety_factor": safety_factor,
        "notes": notes,
    }


# ── Manifest / metrics extractors (thin, best-effort) ─────────────────────────

def n_atoms_from_manifest(manifest: dict) -> int:
    """Total solvated atom count from a run manifest.

    Prefers the solvation charge-audit (``final_solvated.n_atoms``); falls back to
    the ionization water/ion counts, then 0 if nothing is available.
    """
    audit = manifest.get("charge_audit") or {}
    final = audit.get("final_solvated") or {}
    n = final.get("n_atoms")
    if isinstance(n, (int, float)) and n > 0:
        return int(n)
    dry = audit.get("dry_dna") or {}
    n = dry.get("n_atoms")
    return int(n) if isinstance(n, (int, float)) and n > 0 else 0


def total_ns_from_manifest(manifest: dict) -> float:
    """Total simulated nanoseconds = Σ(segment steps) × timestep, + production.

    Minimization steps do not advance time and are excluded.  Uses the relax
    ladder's timestep (2 fs standard / 4 fs fast); adds any recorded production
    extension.
    """
    settings = manifest.get("relax_protocol_settings") or {}
    ts_fs = float(settings.get("timestep_fs") or 2.0)
    seg_steps = sum(int(s.get("steps", 0)) for s in manifest.get("segments", []))
    total_ns = seg_steps * ts_fs / 1e6

    prod = manifest.get("production_extension") or {}
    prod_ns = prod.get("length_ns")
    if isinstance(prod_ns, (int, float)) and prod_ns > 0:
        total_ns += float(prod_ns)
    return total_ns


def latest_ns_per_day(metrics_path: str | Path) -> float | None:
    """Most-recent non-null ``ns_per_day`` from an ``output/metrics.jsonl`` file.

    Returns None if the file is missing/empty or no record carries a value.
    """
    path = Path(metrics_path)
    if not path.is_file():
        return None
    latest: float | None = None
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            v = rec.get("ns_per_day")
            if isinstance(v, (int, float)) and v > 0:
                latest = float(v)
    except OSError:
        return None
    return latest
