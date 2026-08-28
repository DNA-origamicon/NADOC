"""Submission adapters for prepared oxDNA jobs on Alpine and RunPod."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import tarfile
import tempfile
from pathlib import Path

from backend.core.oxdna_job import OxdnaJob, OxdnaStatus

_RUNPOD_TASKS: dict[str, asyncio.Task] = {}


async def _put_text(conn, text: str, remote_path: str) -> None:
    fd, name = tempfile.mkstemp(prefix="nadoc-oxdna-remote-", suffix=".txt")
    os.close(fd)
    path = Path(name)
    try:
        path.write_text(text)
        await conn.sftp_put(str(path), remote_path)
    finally:
        path.unlink(missing_ok=True)


def _alpine_script(job: OxdnaJob, specs, remote: str, engine: str, resources: dict,
                   modules: list[str]) -> str:
    q = shlex.quote
    lines = [
        "#!/bin/bash", f"#SBATCH --job-name=nadoc_oxdna_{job.job_id[:8]}",
        f"#SBATCH --partition={resources['partition']}",
        f"#SBATCH --qos={resources['qos']}",
        f"#SBATCH --time={resources['walltime']}",
        f"#SBATCH --cpus-per-task={resources['cores']}",
        f"#SBATCH --mem={resources['mem_gb']}G",
        f"#SBATCH --output={remote}/slurm_%j.out",
    ]
    if resources.get("gpus", 0):
        gres = resources.get("gres") or f"gpu:{resources['gpus']}"
        lines.append(f"#SBATCH --gres={gres}")
    lines += ["", "set -euo pipefail", "source /etc/profile", "module purge"]
    if modules:
        lines.append("module load " + " ".join(map(shlex.quote, modules)))
    lines += [f"export LD_LIBRARY_PATH={q(str(Path(engine).parent.parent / 'lib'))}:${{LD_LIBRARY_PATH:-}}",
              f"cd {q(remote)}", "echo running > nadoc_status"]
    for idx, spec in enumerate(specs):
        seed = "conf.dat" if idx == 0 else f"{specs[idx - 1].name}/last_conf.dat"
        lines += [f"test -s {q(seed)}", f"echo stage:{spec.name} > nadoc_status",
                  f"(cd {q(spec.name)} && {q(engine)} input.txt) > {q(spec.name + '/stdout.log')} 2> {q(spec.name + '/stderr.log')}"]
    lines += ["echo completed > nadoc_status"]
    return "\n".join(lines) + "\n"


async def submit_alpine(job: OxdnaJob, workspace: Path, specs) -> None:
    """Use the already-authenticated singleton connection; never reconnect here."""
    from backend.core import cluster_config, cluster_oxdna_build, cluster_ssh
    from backend.core.runpod_oxdna import stage_inputs

    conn = cluster_ssh.get_manager()
    if not conn.is_connected():
        raise RuntimeError("Not connected to Alpine — sign in once in the wizard.")
    profile = cluster_config.load_profiles(workspace).get(job.cluster_name or "alpine")
    if profile is None:
        raise RuntimeError(f"Unknown cluster profile {job.cluster_name!r}")
    partition = profile.partition(job.partition or profile.default_partition)
    if partition is None:
        raise RuntimeError(f"Unknown Alpine partition {job.partition!r}")
    defaults = {
        "partition": partition.name, "qos": profile.default_qos,
        "walltime": "02:00:00", "cores": 4, "mem_gb": 16,
        "gpus": 1 if partition.kind == "gpu" else 0,
    }
    if partition.gres_type and defaults["gpus"]:
        defaults["gres"] = f"gpu:{partition.gres_type}:1"
    resources = {**defaults, **(job.requested_resources or {})}
    paths = cluster_config.resolve_paths(profile, conn.user, job.job_id)
    remote = paths["scratch_dir"]
    await conn.mkdir_p(remote)
    job_dir = job.job_dir(workspace)
    fd, archive_name = tempfile.mkstemp(prefix="nadoc-oxdna-alpine-", suffix=".tar.gz")
    os.close(fd)
    archive = Path(archive_name)
    try:
        with tarfile.open(archive, "w:gz", compresslevel=1) as bundle:
            for path in job_dir.iterdir():
                if path.is_file() and not path.name.startswith("job.json"):
                    bundle.add(path, arcname=path.name, recursive=False)
        await conn.sftp_put(str(archive), f"{remote}/prepared.tar.gz")
    finally:
        archive.unlink(missing_ok=True)
    result = await conn.run(f"cd {shlex.quote(remote)} && tar xzf prepared.tar.gz && rm prepared.tar.gz")
    if result.rc != 0:
        raise RuntimeError((result.stderr or result.stdout)[-800:])
    for relative, content in stage_inputs(job_dir, specs, remote).items():
        await _put_text(conn, content, f"{remote}/{relative}")
    build_dir = cluster_oxdna_build.build_dir_for(profile, conn.user, "oxdna-adaptive")
    engine = f"{build_dir}/install/bin/oxDNA"
    script = _alpine_script(job, specs, remote, engine, resources,
                             profile.modules_for(partition.kind == "gpu"))
    await _put_text(conn, script, f"{remote}/submit.sbatch")
    submitted = await conn.run(f"cd {shlex.quote(remote)} && sbatch submit.sbatch")
    match = re.search(r"Submitted batch job (\d+)", submitted.stdout or "")
    if not match:
        raise RuntimeError((submitted.stderr or submitted.stdout or "sbatch failed")[-800:])
    job.slurm_job_id = match.group(1)
    job.remote_scratch_dir = remote
    job.resources = resources
    job.status = OxdnaStatus.running
    job.error = None
    job.save(workspace)


def start_runpod(job: OxdnaJob, workspace: Path, specs) -> None:
    from backend.api import routes_runpod
    if not routes_runpod._SESSION.is_connected():  # noqa: SLF001
        raise RuntimeError("Not connected to RunPod — connect in the wizard first.")
    if not job.runpod_volume_id and not routes_runpod._SESSION.network_volume_id:  # noqa: SLF001
        raise RuntimeError("Choose a RunPod network volume first.")
    if not job.runpod_gpu_key or not job.runpod_quoted_rate_usd_per_hour:
        raise RuntimeError("Choose an available RunPod GPU with a live price quote.")
    job.status = OxdnaStatus.running
    job.error = None
    job.save(workspace)
    task = asyncio.create_task(_runpod(job.job_id, workspace, specs), name=f"oxdna-runpod-{job.job_id}")
    _RUNPOD_TASKS[job.job_id] = task
    task.add_done_callback(lambda _task: _RUNPOD_TASKS.pop(job.job_id, None))


async def _runpod(job_id: str, workspace: Path, specs) -> None:
    from backend.api import routes_runpod
    from backend.core.runpod_oxdna import CampaignLedger, run_prepared_job_on_pod, target_for_gpu
    job = OxdnaJob.load(job_id, workspace)
    session = routes_runpod._SESSION  # noqa: SLF001
    try:
        def pod_created(pod_id: str, _rate: float) -> None:
            live = OxdnaJob.load(job_id, workspace)
            live.runpod_pod_id = pod_id
            live.save(workspace)
        await run_prepared_job_on_pod(
            client=session.require(), network_volume_id=job.runpod_volume_id or session.network_volume_id,
            target=target_for_gpu(job.runpod_gpu_key),
            quoted_rate_usd_per_hour=job.runpod_quoted_rate_usd_per_hour,
            ledger=CampaignLedger(job.job_dir(workspace) / "runpod_spend.json",
                                  cap_usd=job.runpod_budget_usd or 5.0),
            job_id=job_id, job_dir=job.job_dir(workspace), specs=specs,
            patch_path=workspace.parent / "scripts" / "anm-oxdna-cuda13.patch",
            result_dir=job.job_dir(workspace), on_pod_created=pod_created,
        )
        job = OxdnaJob.load(job_id, workspace)
        job.status = OxdnaStatus.completed
        job.runpod_pod_id = None
        job.runpod_final_cost_usd = CampaignLedger(job.job_dir(workspace) / "runpod_spend.json").spent_usd()
        for stage in job.stages:
            stage.status = "done"
        job.save(workspace)
    except Exception as exc:
        job = OxdnaJob.load(job_id, workspace)
        job.status = OxdnaStatus.failed
        job.error = f"RunPod execution failed: {exc}"
        job.runpod_pod_id = None
        job.save(workspace)
