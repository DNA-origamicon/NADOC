"""Compute-cluster profiles — static description of an HPC target (host, scheduler,
filesystem layout, module loads, partitions/QoS/billing).

This is the *config* half of the Alpine remote-execution backend (see
``memory/project_alpine_cluster_submission.md``).  It holds **no credentials** —
only the durable, publishable facts about a cluster.  The live SSH session and
secrets live in ``backend/core/cluster_ssh.py``.

A profile is loaded from ``workspace/clusters.json`` if present, else the embedded
**Alpine** default (CU Research Computing) is used.  ``$USER`` in the filesystem
base paths is substituted at path-resolution time, not at load time, so one profile
serves any account.

Everything here is pure and offline — no network, no import-time side effects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path


@dataclass(frozen=True)
class Partition:
    """One SLURM partition's capabilities (used later by the resource decision tree)."""

    name: str
    kind: str            # "cpu" | "gpu"
    max_cores: int
    mem_per_core_gb: float = 0.0
    gpus: int = 0
    gpu_model: str = ""
    # SLURM GRES type token — aa100 REQUIRES a typed GRES (``gpu:a100-40gb:N``),
    # it rejects a bare ``gpu:N``.  None → emit the untyped form.
    gres_type: str = ""
    # QoS names this partition actually accepts.  Alpine validates QoS PER PARTITION,
    # not just per kind — and namespaces them by partition family (``acpu`` takes
    # ``cpu-normal``/``cpu-long``, ``amem`` takes ``mem-*``, the GPU partitions take
    # ``gpu-*``).  Empty → fall back to the kind-based split.
    allowed_qos: list[str] = field(default_factory=list)
    # Per-GPU billing rate (SU/GPU-hour), overriding the profile-wide value.
    # Alpine's newer GPUs are NOT billed at the A100 rate: ah200 bills 12.63 SU per
    # core-hour vs 6.13 for aa100, so one profile-wide number under-quotes an H200 job
    # by ~4x.  0.0 → fall back to ``ClusterProfile.su_per_gpu_hour``.
    su_per_gpu_hour: float = 0.0


@dataclass(frozen=True)
class QoS:
    """One SLURM QoS tier — the walltime ceiling matters for auto-walltime (Phase 2)."""

    name: str
    max_walltime_h: int


@dataclass(frozen=True)
class ClusterProfile:
    """Durable description of a compute cluster.  No credentials.

    ``project_base`` / ``scratch_base`` are templates containing the literal token
    ``$USER``; call :func:`resolve_paths` to bind a username + job id.
    """

    name: str
    host: str
    scheduler: str                       # "slurm"
    project_base: str                    # persistent, small   (results kept here)
    scratch_base: str                    # fast, auto-purged   (jobs run here)
    module_loads: list[str]              # CPU sbatch header (MPI build) `module load ...`
    default_partition: str
    default_qos: str
    partitions: list[Partition] = field(default_factory=list)
    qos_tiers: list[QoS] = field(default_factory=list)
    # Billing: cost = cores*hours*su_per_core_hour + gpus*hours*su_per_gpu_hour
    su_per_core_hour: float = 1.0
    su_per_gpu_hour: float = 0.0
    # GPU (aa100/…) needs a CUDA / GPU-resident NAMD build, NOT the CPU MPI build in
    # ``module_loads`` — else `+devices` FATALs with "GPUresident not supported on
    # regular multicore builds".  Empty → fall back to ``module_loads``.
    gpu_module_loads: list[str] = field(default_factory=list)
    # Absolute path to a privately-built NAMD, used INSTEAD of a bare ``namd3`` from a
    # module's PATH.  Alpine ships only namd/2.14 and namd/3.0.1_cpu — there is no
    # CUDA NAMD module at all — so GPU-resident there requires a build the user owns
    # (see project_alpine_cluster_submission.md).  Empty → plain ``namd3``.
    namd_bin: str = ""
    gpu_namd_bin: str = ""          # GPU-specific override; falls back to namd_bin

    def namd_command(self, gpu: bool) -> str:
        """The NAMD executable to invoke for this target.

        A private build is addressed by absolute path because it is not on any
        module's PATH; everything else keeps the bare name so a module provides it.
        """
        if gpu and self.gpu_namd_bin:
            return self.gpu_namd_bin
        return self.namd_bin or "namd3"

    def modules_for(self, gpu: bool) -> list[str]:
        """`module load` set for the sbatch header, by target build.

        GPU targets get ``gpu_module_loads`` (a CUDA/GPU-resident NAMD build) when it
        is set; everything else (and any profile that doesn't declare a GPU set) uses
        ``module_loads``.  This is what makes a GPU submission load a build that
        actually supports the ``GPUresident``/``+devices`` exec path.
        """
        if gpu and self.gpu_module_loads:
            return list(self.gpu_module_loads)
        return list(self.module_loads)

    def partition(self, name: str) -> Partition | None:
        return next((p for p in self.partitions if p.name == name), None)

    def qos(self, name: str) -> QoS | None:
        return next((q for q in self.qos_tiers if q.name == name), None)

    def qos_for(self, kind: str, tier: str) -> QoS | None:
        """Resolve a QoS tier ("normal"|"long"|"testing") for a partition kind.

        Alpine namespaces QoS by partition family — GPU partitions require
        ``gpu-<tier>`` and (since the 2026 rename) CPU partitions require
        ``cpu-<tier>``; SLURM rejects the bare names on both.  Try ``<kind>-<tier>``
        first, then fall back to the plain tier so this stays correct for clusters
        that don't namespace their QoS at all.
        """
        prefixed = self.qos(f"{kind}-{tier}")
        if prefixed is not None:
            return prefixed
        return self.qos(tier)

    def qos_tiers_for_kind(self, kind: str) -> list[QoS]:
        """QoS tiers a partition of ``kind`` may use — for the review-card dropdown.

        Alpine namespaces GPU QoS as ``gpu-*``; SLURM rejects the plain names on GPU
        partitions and the ``gpu-*`` names on CPU partitions.  So GPU kind → only the
        ``gpu-*`` tiers, CPU kind → only the plain tiers.
        """
        if kind == "gpu":
            return [q for q in self.qos_tiers if q.name.startswith("gpu-")]
        return [q for q in self.qos_tiers if not q.name.startswith("gpu-")]

    def qos_tiers_for_partition(self, name: str) -> list[QoS]:
        """QoS tiers a SPECIFIC partition accepts — the correct source for the
        review-card dropdown.

        Alpine validates QoS per partition (``acpu`` takes only cpu-normal/cpu-long,
        not the amem or testing tiers), so prefer the partition's ``allowed_qos``
        allow-list; fall back to the kind-based split for profiles without one.
        """
        part = self.partition(name)
        if part is None:
            return []
        if part.allowed_qos:
            return [q for n in part.allowed_qos if (q := self.qos(n)) is not None]
        return self.qos_tiers_for_kind(part.kind)


# ── Embedded Alpine profile (CURC) — Appendix data from the plan ──────────────────

def alpine_profile() -> ClusterProfile:
    """The built-in CU Research Computing "Alpine" profile.

    GPU-first per the plan's decision #3 — NADOC's local pipeline is CUDA and NAMD3
    GPU-resident is far faster than the CPU build.  The default GPU partition moved
    aa100 -> ah200 on 2026-08-06 (see ``default_partition`` below).
    """

    return ClusterProfile(
        name="alpine",
        host="login.rc.colorado.edu",
        scheduler="slurm",
        project_base="/projects/$USER/nadoc_jobs",
        scratch_base="/scratch/alpine/$USER/nadoc_jobs",
        module_loads=[
            "gcc/14.2.0",
            "openmpi/5.0.6",
            "namd/3.0.1_cpu",
        ],
        # GPU-resident NAMD build for aa100/al40 (the `+devices` exec path).  Best-
        # guess by CURC's `_cpu`→`_gpu` module-naming convention; the exact string is
        # confirmable live via GET /api/cluster/namd-modules (`module avail namd`).
        # If wrong, the sbatch's `module load` fails and increment-6 error surfacing
        # shows it on the frontend — override here or in workspace/clusters.json.
        gpu_module_loads=[
            "gcc/14.2.0",
            "namd/3.0.1_gpu",
        ],
        # ah200 (H200) is the default since 2026-08-06.  Live `sbatch --test-only` for
        # a 63k-atom / 200 ns job: aa100 would start in 13 d 16 h (630 jobs pending),
        # ah200 immediately.  It bills ~3x the A100 rate per GPU-hour, but finishes the
        # same job ~15 days sooner and at ~2.5x the throughput, so the SU cost per ns is
        # comparable while the wall-clock is not close.  The availability popup shows
        # both axes; override per job from the review card.
        default_partition="ah200",
        default_qos="gpu-normal",
        partitions=[
            # `acpu` REPLACED `amilan`/`amilan128c` in the 2026 expansion — live-confirmed
            # 2026-08-06 via `scontrol show node`: the cluster reports aa100, acompile,
            # acpu, ah200, al40, amem, ami100, artxpro6000, atesting, dtn, gh200, and NO
            # amilan.  Submitting to amilan now fails at sbatch.  QoS was renamed with it
            # (cpu-normal/cpu-long, mem-normal/mem-long).
            Partition("acpu", "cpu", max_cores=64, mem_per_core_gb=3.8, allowed_qos=["cpu-normal", "cpu-long"]),
            Partition("amem", "cpu", max_cores=128, mem_per_core_gb=21.5, allowed_qos=["mem-normal", "mem-long"]),
            # aa100 GRES type "a100-40gb" + gpu-* QoS are live-confirmed; the others
            # are best-guess Alpine tokens.
            Partition("aa100", "gpu", max_cores=64, mem_per_core_gb=3.75, gpus=3, gpu_model="NVIDIA A100", gres_type="a100-40gb", allowed_qos=["gpu-normal", "gpu-long", "gpu-testing"]),
            Partition("ami100", "gpu", max_cores=64, mem_per_core_gb=3.75, gpus=3, gpu_model="AMD MI100", gres_type="mi100", allowed_qos=["gpu-normal", "gpu-long", "gpu-testing"]),
            Partition("al40", "gpu", max_cores=64, mem_per_core_gb=3.75, gpus=3, gpu_model="NVIDIA L40", gres_type="l40", allowed_qos=["gpu-normal", "gpu-long", "gpu-testing"]),
            # 2026 GPU expansion (CURC alpine-hardware docs).  Both are CU-Boulder-only,
            # 4 GPUs/node on 128-core nodes with 12 GB/core, and — unlike aa100/ami100 —
            # they do NOT offer gpu-testing.  su_per_gpu_hour is scaled from the A100 rate
            # by (billing_weight/core x cores-per-GPU); confirm against `sacctmgr`/sreport.
            Partition("ah200", "gpu", max_cores=128, mem_per_core_gb=12.0, gpus=4, gpu_model="NVIDIA H200", gres_type="h200", allowed_qos=["gpu-normal", "gpu-long"], su_per_gpu_hour=334.0),
            Partition("artxpro6000", "gpu", max_cores=128, mem_per_core_gb=12.0, gpus=4, gpu_model="NVIDIA RTX Pro 6000", gres_type="rtx_pro_6000", allowed_qos=["gpu-normal", "gpu-long"], su_per_gpu_hour=242.0),
            Partition("atesting", "cpu", max_cores=64, mem_per_core_gb=3.75, allowed_qos=["testing"]),
            Partition("atesting_a100", "gpu", max_cores=64, mem_per_core_gb=3.75, gpus=1, gpu_model="NVIDIA A100", gres_type="a100-40gb", allowed_qos=["gpu-testing"]),
        ],
        qos_tiers=[
            # Every family namespaces its QoS; the bare normal/long/mem names were
            # retired with amilan and SLURM now rejects them.
            QoS("cpu-normal", max_walltime_h=24),
            QoS("cpu-long", max_walltime_h=168),
            QoS("mem-normal", max_walltime_h=24),
            QoS("mem-long", max_walltime_h=168),
            QoS("testing", max_walltime_h=1),
            QoS("compile", max_walltime_h=12),
            # GPU partitions (aa100/al40/ami100/…) namespace their QoS as gpu-*
            # (SLURM rejects the plain names on aa100). Ceilings mirror the CPU tiers.
            QoS("gpu-normal", max_walltime_h=24),
            QoS("gpu-long", max_walltime_h=168),
            QoS("gpu-testing", max_walltime_h=1),
        ],
        su_per_core_hour=1.0,
        su_per_gpu_hour=108.2,
    )


# ── (de)serialization + loading ───────────────────────────────────────────────────

def _profile_from_dict(d: dict) -> ClusterProfile:
    return ClusterProfile(
        name=d["name"],
        host=d["host"],
        scheduler=d.get("scheduler", "slurm"),
        project_base=d["project_base"],
        scratch_base=d["scratch_base"],
        module_loads=list(d.get("module_loads", [])),
        namd_bin=d.get("namd_bin", ""),
        gpu_namd_bin=d.get("gpu_namd_bin", ""),
        default_partition=d["default_partition"],
        default_qos=d["default_qos"],
        partitions=[Partition(**p) for p in d.get("partitions", [])],
        qos_tiers=[QoS(**q) for q in d.get("qos_tiers", [])],
        su_per_core_hour=d.get("su_per_core_hour", 1.0),
        su_per_gpu_hour=d.get("su_per_gpu_hour", 0.0),
        gpu_module_loads=list(d.get("gpu_module_loads", [])),
    )


def load_profiles(workspace_dir: str | Path | None = None) -> dict[str, ClusterProfile]:
    """Return ``{name: ClusterProfile}``.

    Reads ``<workspace_dir>/clusters.json`` if it exists (a JSON list of profile
    objects); otherwise returns just the embedded Alpine profile.  Alpine is always
    present as a fallback even when a custom file omits it.
    """

    profiles: dict[str, ClusterProfile] = {"alpine": alpine_profile()}
    if workspace_dir is None:
        return profiles
    path = Path(workspace_dir) / "clusters.json"
    if path.is_file():
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return profiles
        entries = raw if isinstance(raw, list) else raw.get("clusters", [])
        for entry in entries:
            try:
                prof = _profile_from_dict(entry)
            except (KeyError, TypeError):
                continue
            profiles[prof.name] = prof
    return profiles


def get_profile(name: str, workspace_dir: str | Path | None = None) -> ClusterProfile:
    """Look up one profile by name (raises ``KeyError`` if unknown)."""

    return load_profiles(workspace_dir)[name]


# ── path resolution ───────────────────────────────────────────────────────────────

def _sub_user(template: str, user: str) -> str:
    return template.replace("$USER", user).replace("${USER}", user)


def resolve_paths(profile: ClusterProfile, user: str, job_id: str) -> dict[str, str]:
    """Bind ``$USER`` + a job id into the two-filesystem layout.

    Returns ``{"project_dir": ..., "scratch_dir": ...}`` — the persistent results
    dir and the fast auto-purged run dir for this job.
    """

    if not user:
        raise ValueError("user must be non-empty to resolve cluster paths")
    if not job_id:
        raise ValueError("job_id must be non-empty to resolve cluster paths")
    project = _sub_user(profile.project_base, user).rstrip("/")
    scratch = _sub_user(profile.scratch_base, user).rstrip("/")
    return {
        "project_dir": f"{project}/{job_id}",
        "scratch_dir": f"{scratch}/{job_id}",
    }


def profile_with_gpu_modules(profile: ClusterProfile, modules: list[str]) -> ClusterProfile:
    """Return a copy with ``module_loads`` swapped (e.g. CPU→GPU NAMD build).

    Small convenience so Phase 2's script generator can pick the GPU module set
    without mutating the shared embedded profile.
    """

    return replace(profile, module_loads=list(modules))
