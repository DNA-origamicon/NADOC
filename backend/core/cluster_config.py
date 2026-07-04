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
    # not just per kind: amilan rejects ``testing``/``mem`` (live-confirmed 2026-07-03:
    # "The amilan partition accepts the following QoS values: admin or normal or long").
    # Empty → fall back to the kind-based split.
    allowed_qos: list[str] = field(default_factory=list)


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

        Alpine's GPU partitions (aa100/al40/…) require the ``gpu-<tier>`` QoS names
        (SLURM rejects the plain ones there); CPU partitions use ``<tier>``.  Falls
        back to the plain tier when a profile doesn't define the gpu- variant, so
        this stays correct for clusters that don't namespace GPU QoS.
        """
        if kind == "gpu":
            gpu = self.qos(f"gpu-{tier}")
            if gpu is not None:
                return gpu
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

        Alpine validates QoS per partition (amilan takes only normal/long, not the
        other CPU tiers), so prefer the partition's ``allowed_qos`` allow-list; fall
        back to the kind-based split for partitions/profiles that don't declare one.
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

    GPU-first (the ``aa100`` A100 partition) per the plan's decision #3 — NADOC's
    local pipeline is CUDA and NAMD3 GPU-resident is far faster than the CPU build.
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
        default_partition="aa100",
        default_qos="gpu-normal",
        partitions=[
            # allowed_qos: amilan is live-confirmed (normal/long only — rejects
            # testing/mem/compile); the rest are best-guess by partition family and
            # should be corrected against live sbatch errors as they surface.
            Partition("amilan", "cpu", max_cores=64, mem_per_core_gb=3.75, allowed_qos=["normal", "long"]),
            Partition("amilan128c", "cpu", max_cores=128, mem_per_core_gb=2.01, allowed_qos=["normal", "long"]),
            Partition("amem", "cpu", max_cores=128, mem_per_core_gb=21.5, allowed_qos=["normal", "long", "mem"]),
            # aa100 GRES type "a100-40gb" + gpu-* QoS are live-confirmed; the others
            # are best-guess Alpine tokens.
            Partition("aa100", "gpu", max_cores=64, mem_per_core_gb=3.75, gpus=3, gpu_model="NVIDIA A100", gres_type="a100-40gb", allowed_qos=["gpu-normal", "gpu-long", "gpu-testing"]),
            Partition("ami100", "gpu", max_cores=64, mem_per_core_gb=3.75, gpus=3, gpu_model="AMD MI100", gres_type="mi100", allowed_qos=["gpu-normal", "gpu-long", "gpu-testing"]),
            Partition("al40", "gpu", max_cores=64, mem_per_core_gb=3.75, gpus=3, gpu_model="NVIDIA L40", gres_type="l40", allowed_qos=["gpu-normal", "gpu-long", "gpu-testing"]),
            Partition("atesting", "cpu", max_cores=64, mem_per_core_gb=3.75, allowed_qos=["testing"]),
            Partition("atesting_a100", "gpu", max_cores=64, mem_per_core_gb=3.75, gpus=1, gpu_model="NVIDIA A100", gres_type="a100-40gb", allowed_qos=["gpu-testing"]),
        ],
        qos_tiers=[
            # CPU partitions (amilan/amem/…) use the plain tier names.
            QoS("normal", max_walltime_h=24),
            QoS("long", max_walltime_h=168),
            QoS("mem", max_walltime_h=168),
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
