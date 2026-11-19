"""Resource choices for the solver launch wizard, shared with admission checks."""
import math
from types import SimpleNamespace
from backend.core.solver_resources import GIB, estimate_resources


def alpine_choices(workspace):
    from backend.core.cluster_config import load_profiles
    profile = load_profiles(workspace)["alpine"]
    rows = []
    for part in profile.partitions:
        rows.append(dict(id=part.name, label=part.name, kind=part.kind, gpu_model=part.gpu_model, gres_type=part.gres_type,
                         cuda="NVIDIA" in part.gpu_model, vram_gb=part.gpu_vram_gb,
                         max_cores=part.max_cores,
                         mem_per_core_gb=part.mem_per_core_gb,
                         max_ram_gib=math.floor(part.max_cores * part.mem_per_core_gb),
                         qos=[dict(name=q.name, minutes=int(q.max_walltime_h * 60))
                              for q in profile.qos_tiers_for_partition(part.name)]))
    return rows


def runtime_preview(engine, sites, options):
    """Existing solver progress heuristic, explicitly NOT a GPU throughput model."""
    keys = dict(nonlinear=True, n_steps=20, with_rmsf=True, dynamics=False,
                hydrodynamics=False, hydro_coarse_bp=None, tails=False,
                coarse_steps=100000, fine_steps=0)
    job = SimpleNamespace(n_nucleotides=sites,
                          **{k: getattr(options, k, v) for k, v in keys.items()})
    if engine == 'snupi':
        from backend.core.snupi_runner import _estimate_seconds
        basis = 'SNUPI reference CPU heuristic; no per-node speed calibration'
    else:
        from backend.core.mrdna_runner import _estimate_seconds
        basis = 'mrDNA RTX 3080 Ti reference heuristic; no per-GPU speed calibration'
    return dict(seconds=_estimate_seconds(job), basis=basis,
                note='Rough solver runtime, excluding queue, pod startup, transfers and environment checks. Large-system extrapolation can be inaccurate.')


def resource_preview(engine, design, options, workspace):
    need = estimate_resources(engine, design, options)
    return dict(ram_gib=need.ram / GIB, vram_gib=need.gpu / GIB,
                disk_gib=need.disk / GIB, min_ram_gib=math.ceil(need.ram / GIB / .8),
                min_vram_gb=math.ceil(need.gpu / 1e9 / .85),
                alpine=alpine_choices(workspace), runtime=runtime_preview(engine, need.sites, options))
