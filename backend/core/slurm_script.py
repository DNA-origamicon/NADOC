"""Generate an Alpine (SLURM) sbatch script for a prepared NADOC MD job.

The other *offline* half of Phase 2 (see
``memory/project_alpine_cluster_submission.md``).  A NADOC MD package already
contains every NAMD input on disk: one minimization ``.conf`` plus one ``.conf``
per relaxation segment (each referencing the previous segment's restart coords by
relative path).  So the remote job is a single ``sbatch`` that ``cd``s into the
uploaded package on scratch and runs those confs **in order**, redirecting each to
its ``.log`` — exactly what the local runner does, minus the between-segment
Python health/reconcile bookkeeping (which is advisory-only and recomputed locally
after fetch — see the plan's decision #1).

Pure and offline: builds a string from a parsed manifest + a ClusterProfile + a
resource dict (from ``cluster_resources.recommend``).  No file IO, no network.
"""

from __future__ import annotations

import re

from backend.core.cluster_config import ClusterProfile

# A declash design needs a mid-chain Python step (``rebuild_declashed_references``)
# between minimization and the segments — that cannot run inside a plain sbatch on
# a node without NADOC.  Remote submission of declash jobs is therefore rejected
# here; Phase 3 can stage the rebuilt package locally before upload if needed.
_DECLASH_UNSUPPORTED_MSG = (
    "Declash jobs require a mid-chain reference rebuild that cannot run in a bare "
    "sbatch; run this design locally, or stage the declashed package before remote "
    "submission (not yet supported)."
)


def sanitize_job_name(raw: str) -> str:
    """SLURM-safe job name: keep [A-Za-z0-9._-], collapse the rest to '_'.

    Raises ValueError on an empty / all-illegal name.
    """
    if raw is None:
        raise ValueError("job name must be non-empty")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(raw)).strip("_")
    if not cleaned:
        raise ValueError(f"job name {raw!r} has no usable characters")
    return cleaned


def is_gpu_target(profile: ClusterProfile, resources: dict) -> bool:
    """True when the run uses the GPU-resident exec path.

    Single source of truth for the GPU/CPU branch: the sbatch exec line, the GRES
    directives, AND the conf amendment (whether staged confs keep ``GPUresident``)
    must all agree, or a CPU run inherits a ``GPUresident on`` conf and FATALs at the
    first fast segment.  Raises ValueError for an unknown partition.
    """
    part = profile.partition(resources["partition"])
    if part is None:
        raise ValueError(
            f"partition {resources['partition']!r} is not in profile {profile.name!r}"
        )
    return part.kind == "gpu"


def _segment_chain(manifest: dict) -> list[str]:
    """Ordered conf base-names to run: minimization first, then every segment."""
    min_name = (manifest.get("minimization") or {}).get("name")
    if not min_name:
        raise ValueError("manifest has no minimization.name")
    chain = [min_name]
    for seg in manifest.get("segments", []):
        name = seg.get("name")
        if not name:
            raise ValueError("manifest segment missing a name")
        chain.append(name)
    if len(chain) == 1:
        raise ValueError("manifest has no segments to run")
    return chain


def _sbatch_directives(job_name: str, resources: dict, gpu: bool) -> list[str]:
    lines = [
        f"#SBATCH --job-name={job_name}",
        f"#SBATCH --output={job_name}_%j.out",
        f"#SBATCH --error={job_name}_%j.err",
        f"#SBATCH --partition={resources['partition']}",
        "#SBATCH --nodes=1",
        f"#SBATCH --ntasks={resources['cores']}",
        f"#SBATCH --time={resources['walltime']}",
        f"#SBATCH --mem={resources['mem_gb']}GB",
        f"#SBATCH --qos={resources['qos']}",
    ]
    if gpu:
        n_gpus = resources.get("gpus", 1)
        # aa100 requires a TYPED GRES (gpu:a100-40gb:N); a bare gpu:N is rejected.
        gres_type = resources.get("gres_type") or ""
        gres = f"gpu:{gres_type}:{n_gpus}" if gres_type else f"gpu:{n_gpus}"
        lines.append(f"#SBATCH --gres={gres}")
    return lines


def _module_block(profile: ClusterProfile, gpu: bool) -> list[str]:
    lines = ["module purge"]
    mods = profile.modules_for(gpu)
    if mods:
        lines.append("module load " + " ".join(mods))
    return lines


def _looks_cpu_only(modules: list[str]) -> bool:
    """True if a NAMD module in the set looks CPU-only (``namd/..._cpu``)."""
    return any(
        "namd" in m.lower() and (m.lower().endswith("_cpu") or "_cpu" in m.lower())
        for m in modules
    )


def _exec_line(conf: str, log: str, resources: dict, gpu: bool) -> str:
    """The NAMD invocation for one conf.

    GPU: NAMD3 GPU-resident, ``+p<cores> +setcpuaffinity +devices 0[,1,...]``.
    CPU: OpenMPI build, ``mpirun -np $SLURM_NTASKS namd3``.
    """
    if gpu:
        cores = resources.get("cores", 1)
        gpus = resources.get("gpus", 1)
        devices = ",".join(str(i) for i in range(max(1, gpus)))
        return f"namd3 +p{cores} +setcpuaffinity +devices {devices} {conf}.conf > {log} 2>&1"
    return f"mpirun -np $SLURM_NTASKS namd3 {conf}.conf > {log} 2>&1"


def generate_sbatch(
    manifest: dict,
    profile: ClusterProfile,
    resources: dict,
    remote_scratch_dir: str,
    *,
    job_name: str | None = None,
    resume_conf_for: dict[str, str] | None = None,
) -> str:
    """Build the sbatch script string for a prepared job.

    Args:
        manifest: the parsed ``manifest.json`` (minimization + segments + name_stem).
        profile:  the target cluster (module loads; partition kind → GPU vs CPU).
        resources: a ``cluster_resources.recommend`` dict.
        remote_scratch_dir: absolute scratch path the package was mirrored to.
        job_name: overrides the sanitized ``name_stem``.
        resume_conf_for: optional ``{segment_name: resume_conf_base}`` — for a
            mid-segment resume, run the resume conf (which reads the segment's restart
            checkpoint) instead of the fresh conf.  The skip guard still keys on the
            segment's final ``output/<name>.coor`` and the resume run logs to
            ``<name>.resume.log`` (so the partial ``<name>.log`` is preserved).

    Raises ValueError for a declash manifest, an empty segment chain, or an unknown
    partition.
    """
    resume_conf_for = resume_conf_for or {}
    if manifest.get("declash"):
        raise ValueError(_DECLASH_UNSUPPORTED_MSG)

    name_stem = manifest.get("name_stem") or "nadoc_md"
    job_name = sanitize_job_name(job_name if job_name is not None else name_stem)

    gpu = is_gpu_target(profile, resources)

    chain = _segment_chain(manifest)

    lines: list[str] = ["#!/bin/bash"]
    lines += _sbatch_directives(job_name, resources, gpu)
    # InfiniBand only matters for multi-node CPU/MPI jobs; a single-node GPU-resident
    # run doesn't need it, and over-constraining node selection can make aa100 report
    # "node configuration not available".
    if not gpu:
        lines.append("#SBATCH --constraint=ib")   # InfiniBand (OpenMPI)
    lines.append("")
    # A GPU run needs a GPU-resident NAMD module; if the resolved GPU module set
    # still looks CPU-only, the `+devices` exec line will FATAL — warn loudly rather
    # than pair a GPU exec line with a CPU build.
    if gpu and _looks_cpu_only(profile.modules_for(gpu)):
        lines.append(
            "# WARNING: GPU partition selected but the NAMD module looks CPU-only "
            "(namd/*_cpu). Confirm the GPU module via GET /api/cluster/namd-modules "
            "and set gpu_module_loads in workspace/clusters.json before submitting."
        )
        lines.append("")
    lines += [
        # Source the login profile BEFORE enabling errexit — Alpine's /etc/profile
        # references unbound vars (e.g. HISTCONTROL, line 47) that abort the job
        # under `set -u` before NAMD ever runs (live-confirmed 2026-07-03: a job
        # died with only "/etc/profile: line 47: HISTCONTROL: unbound variable").
        # We keep errexit + pipefail to catch real NAMD/module failures, but drop
        # `-u`: HPC profile/module scripts routinely reference unbound variables.
        "source /etc/profile",
        "set -eo pipefail",
        "export SLURM_EXPORT_ENV=ALL",      # required for OpenMPI
        "",
        *_module_block(profile, gpu),
        "",
        f"cd '{remote_scratch_dir}'",
        # A freshly-staged package has no output/ (local run artifacts are excluded
        # from the upload); each conf writes to output/<name>.* so it must exist.
        "mkdir -p output",
        "",
        "# NADOC MD ladder: minimization, then each relaxation segment in order.",
        "# Each conf reads the previous segment's restart coords by relative path.",
        "# Each step is skipped if its final output/<conf>.coor already exists, so a",
        "# resubmit onto the same scratch resumes at the first unfinished step (the",
        "# interrupted one re-runs in full from the previous step's coords). This is",
        "# what makes auto-resubmit-on-TIMEOUT a slowdown, not a lost run.",
    ]
    for conf in chain:
        resume_conf = resume_conf_for.get(conf)
        run_conf = resume_conf or conf
        log = f"{conf}.resume.log" if resume_conf else f"{conf}.log"
        verb = "resuming from checkpoint" if resume_conf else "running"
        lines.append(f'if [ -f "output/{conf}.coor" ]; then')
        lines.append(f'  echo "[NADOC] skip {conf} (already complete)"')
        lines.append("else")
        lines.append(f'  echo "[NADOC] {verb} {conf}"')
        lines.append("  " + _exec_line(run_conf, log, resources, gpu))
        lines.append("fi")
    lines.append("")
    lines.append('echo "[NADOC] ladder complete"')
    return "\n".join(lines) + "\n"
