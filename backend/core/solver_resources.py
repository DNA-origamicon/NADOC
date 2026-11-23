"""Conservative launch planning for SNUPI/mrDNA, without constructing solver arrays.

The sparse-solver fill and ARBD per-particle allowances are planning envelopes,
not calibrated peak-RSS predictions. Hydrodynamic dense storage uses its measured
model. Count domains independently (including both duplex strands) deliberately:
this overbounds solver sites and fragmented chains in parts and assembly projections.
"""

from dataclasses import dataclass
import math
import shutil
from pathlib import Path

from backend.core.memory_budget import MemoryBudgetExceeded, available_for_work

GIB = 1024**3


@dataclass(frozen=True)
class SolverResources:
    ram: int
    gpu: int
    disk: int
    sites: int


def estimate_resources(engine, design, options):
    lengths = [
        abs(d.end_bp - d.start_bp) + 1 for s in design.strands for d in s.domains
    ]
    lengths += [len(e.sequence or "") for e in design.extensions]
    lengths += [len(x.extra_bases or "") for x in design.crossovers]
    lengths += [
        len(x.extra_bases or "") for x in getattr(design, "forced_ligations", [])
    ]
    lengths += [2 * max(0, ls.delta) for h in design.helices for ls in h.loop_skips]
    n = max(1, sum(lengths))
    if engine == "snupi":
        # Python mesh/COO assembly, sparse factor fill, eigensolver workspace.
        # At BigO-poly's 423,360-nt bound this plans ~60 GiB, above the
        # recorded ~46 GiB NMA peak (docs/solver_cluster_execution.md).
        # A single observation is not a universal sparse-fill calibration.
        ram = GIB + 65536 * n + math.ceil(128 * n**1.5)
        if getattr(options, "dynamics", False) and getattr(
            options, "hydrodynamics", False
        ):
            from backend.physics.snupi_hydrodynamics import estimate_friction_memory_gb

            k = getattr(options, "hydro_coarse_bp", None)
            blobs = sum(math.ceil(size / k) for size in lengths) if k else None
            ram += math.ceil(estimate_friction_memory_gb(n, k, blobs) * 1e9)
        # Dynamics has a fixed sampling schedule; allow cached coordinates/JSON too.
        disk = GIB + n * (100000 if getattr(options, "dynamics", False) else 4096)
        return SolverResources(ram, 0, disk, n)
    if engine != "mrdna":
        raise ValueError(f"Unknown solver: {engine}")
    # Fine uses DNA + orientation particles; nt count overbounds duplex bp count.
    beads = 2 * n if getattr(options, "fine_steps", 0) else n
    frames = (
        getattr(options, "coarse_steps", 100000) + getattr(options, "fine_steps", 0)
    ) // max(1, getattr(options, "output_period", 10000)) + 4
    trajectory = beads * frames * 12
    return SolverResources(
        2 * GIB + 65536 * beads, GIB + 16384 * beads, GIB + 4 * trajectory + 8192 * n, n
    )


def check_resources(engine, design, options, workspace):
    """Deny before preparation/launch; no geometry or job state is modified."""
    label = "SNUPI" if engine == "snupi" else "mrDNA"
    if design is None:
        raise MemoryBudgetExceeded(
            f"{label} job cannot start: its design snapshot is missing or unreadable."
        )
    need = estimate_resources(engine, design, options)
    target = getattr(options, "execution_target", "local")
    if target == "local":
        ram = available_for_work()
        ram = min(ram, cgroup_available())
    else:
        settings = getattr(
            options,
            "cluster_settings" if target == "alpine" else "runpod_settings",
            None,
        )
        if settings is None:
            settings = (getattr(options, "remote", None) or {}).get("settings", {})
        mem = (
            settings.get("mem_gb", 0) if isinstance(settings, dict) else settings.mem_gb
        )
        ram = int(mem * GIB * 0.8)
    limits = [("RAM", need.ram, ram)]
    if target == "alpine":
        from backend.core.solver_resource_options import alpine_choices
        values = settings if isinstance(settings, dict) else settings.model_dump()
        row = next((row for row in alpine_choices(workspace)
                    if row["id"] == values.get("partition")), None)
        if row is None:
            raise MemoryBudgetExceeded("Unknown Alpine resource; choose a supported partition")
        if engine == "mrdna" and not row["cuda"]:
            raise MemoryBudgetExceeded("mrDNA requires a CUDA GPU partition")
        limits.append(("allocated host RAM", mem * GIB,
                       min(row["max_ram_gib"], values.get("cores", 0) * row["mem_per_core_gb"]) * GIB))
        if need.gpu:
            limits.append(("GPU memory", need.gpu, row["vram_gb"] * 1e9 * .85))
    if target != "local":
        limits.append(
            (
                "local preparation RAM",
                GIB + 4096 * need.sites,
                min(available_for_work(), cgroup_available()),
            )
        )
    # Snapshots/downloads still reside locally for remote jobs.
    limits.append(
        ("local disk space", need.disk, max(0, shutil.disk_usage(workspace).free - GIB))
    )
    if target == "local" and need.gpu:
        from backend.core.md_vram import detect_gpu_activity

        gpu = detect_gpu_activity(devices=str(getattr(options, "device", "0")))
        if not gpu or gpu.get("total_mb") is None or gpu.get("used_mb") is None:
            raise MemoryBudgetExceeded(
                f"{label} job cannot start: available GPU memory could not be measured. Check the selected CUDA device and retry."
            )
        limits.append(
            (
                "GPU memory",
                need.gpu,
                max(0, (gpu["total_mb"] - gpu["used_mb"]) * 1024**2 - 512 * 1024**2),
            )
        )
    exceeded = [
        (name, required, available)
        for name, required, available in limits
        if required > available
    ]
    if exceeded:
        details = "\n".join(
            f"{name}: estimated {required / GIB:.2f} GiB required; {available / GIB:.2f} GiB available after headroom."
            for name, required, available in exceeded
        )
        raise MemoryBudgetExceeded(
            f"{label} job cannot start.\n{details}\nReduce the part/assembly size or sampling, free resources, or select a larger execution target. Estimates include conservative solver overhead."
        )
    return need


def check_snapshot_capacity(job_dir):
    """Refuse a huge saved JSON before parsing it for the detailed estimate."""
    snapshot = Path(job_dir) / "design.json"
    if not snapshot.exists():
        return  # The snapshot loader supplies the missing/unreadable-file error.
    required = 256 * 1024**2 + 8 * snapshot.stat().st_size
    available = min(available_for_work(), cgroup_available())
    if required > available:
        raise MemoryBudgetExceeded(
            f"Job cannot start: reading its saved design needs approximately {required / GIB:.2f} GiB RAM; "
            f"{available / GIB:.2f} GiB is available after headroom. Free memory before retrying."
        )


def cgroup_available():
    """Respect Linux cgroup v2 limits, including tighter parent scopes."""
    try:
        entries = Path("/proc/self/cgroup").read_text().splitlines()
        relative = next(line[3:] for line in entries if line.startswith("0::"))
        root = Path("/sys/fs/cgroup")
        current = root / relative.lstrip("/")
        remaining = math.inf
        while current == root or root in current.parents:
            limit = current / "memory.max"
            if limit.exists():
                raw = limit.read_text().strip()
                if raw != "max":
                    used = int((current / "memory.current").read_text())
                    remaining = min(remaining, max(0, int(raw) - used - GIB))
            if current == root:
                break
            current = current.parent
        return remaining
    except (OSError, ValueError, StopIteration):
        return math.inf


def reserve_resources(need, engine, options):
    """Atomically reserve pending growth so simultaneous launches cannot overbook."""
    from backend.core.memory_budget import reserve

    lease = reserve(
        need.ram,
        kind="simulation",
        label=f"{engine} job",
        gpu_mib=(need.gpu / 1024**2 + 512) if need.gpu else 0,
        devices=str(getattr(options, "device", "0")),
    )
    return _ScopedReservation(lease, need.ram)


class _ScopedReservation:
    def __init__(self, lease, amount):
        self.lease, self.amount = lease, amount

    def __enter__(self):
        from backend.core.memory_budget import SYSTEM_RESERVE_BYTES

        self.lease.__enter__()
        try:
            capacity = cgroup_available()
            if math.isfinite(capacity):
                # Add a sentinel before the budget's zero clipping so oversubscription
                # remains detectable, including this lease and simultaneous launches.
                remaining = available_for_work(
                    capacity + SYSTEM_RESERVE_BYTES + self.amount
                )
                if remaining < self.amount:
                    raise MemoryBudgetExceeded(
                        "Job cannot start: pending jobs exceed the available cgroup RAM limit. Wait for other work or use a larger execution target."
                    )
        except BaseException:
            self.lease.__exit__(None, None, None)
            raise
        return self

    def bind_child(self, pid):
        self.lease.bind_child(pid)

    def __exit__(self, *args):
        return self.lease.__exit__(*args)


def launch_reserved_detached(resources, job, workspace, module, repo_root, registry):
    from backend.core import simulation_runtime as runtime

    reservation = reserve_resources(resources, "SNUPI", job)
    reservation.__enter__()

    def spawned(proc):
        reservation.bind_child(proc.pid)
        registry[job.job_id] = proc.pid

    def finished():
        registry.pop(job.job_id, None)
        reservation.__exit__(None, None, None)

    try:
        job.error = None
        proc = runtime.launch_detached(
            job, workspace, module, repo_root, on_spawn=spawned, on_exit=finished
        )
        if proc is None:
            finished()
    except BaseException:
        finished()
        raise


def launch_reserved_thread(
    resources, job, workspace, target, registry, handle_type, on_stop, before_start
):
    from backend.core import simulation_runtime as runtime

    reservation = reserve_resources(resources, "mrDNA", job)
    reservation.__enter__()

    def run_reserved():
        try:
            target()
        finally:
            reservation.__exit__(None, None, None)

    try:
        launched = runtime.launch_thread(
            job.job_dir(workspace),
            job.job_id,
            run_reserved,
            registry,
            handle_type,
            on_stop,
            name=f"mrdna-runner-{job.job_id}",
            before_start=before_start,
        )
        if not launched:
            reservation.__exit__(None, None, None)
    except BaseException:
        reservation.__exit__(None, None, None)
        raise
