"""Managed Alpine execution for prepared SNUPI/mrDNA jobs.

Scheduler evidence owns remote liveness. Disconnects preserve state. There is no
implicit resubmission or local fallback. Results are downloaded before completion.
"""
from __future__ import annotations

import asyncio
import hashlib
import shutil
import json
from pathlib import Path
import re
import shlex
import tarfile
import tempfile
import threading
import time
import uuid

from backend.core.solver_cluster_config import validate_settings

_ROOT = Path(__file__).resolve().parents[2]
_LOCK = threading.Lock()
_TASKS = set()
_LAST = {}
_ACTIVE = {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING", "REQUEUED", "SUSPENDED"}


def remote_pending(job):
    remote = getattr(job, "remote", None) or {}
    return getattr(job, "execution_target", "local") != "local" and bool(
        remote.get("provisioning") or remote.get("submission_uncertain") or remote.get("downloading")
        or (remote.get("slurm_job_id") and not remote.get("results_collected"))
        or (remote.get("pod_id") and not remote.get("pod_destroyed"))
        or job.status.value in {"preparing", "running"}
    )


def job_class(engine):
    if engine == "snupi":
        from backend.core.snupi_job import SnupiJob
        return SnupiJob
    if engine == "mrdna":
        from backend.core.mrdna_job import MrdnaJob
        return MrdnaJob
    raise ValueError("Unknown solver")


def script(engine, job, remote, config, partition):
    q = shlex.quote
    minutes = config.walltime_minutes
    lines = ["#!/bin/bash", f"#SBATCH --job-name=nadoc_{engine}_{job.job_id}",
             f"#SBATCH --partition={config.partition}", f"#SBATCH --qos={config.qos}",
             f"#SBATCH --account={config.account}", f"#SBATCH --cpus-per-task={config.cores}",
             f"#SBATCH --mem={config.mem_gb}G", f"#SBATCH --time={minutes}",
             "#SBATCH --nodes=1", "#SBATCH --ntasks=1", "#SBATCH --output=slurm.out"]
    if partition.kind == "gpu":
        lines.append(f"#SBATCH --gres=gpu:{partition.gres_type}:1" if partition.gres_type else "#SBATCH --gres=gpu:1")
    lines += ["set -euo pipefail", f"cd {q(remote)}", "export PYTHONUNBUFFERED=1",
              f"export OPENBLAS_NUM_THREADS={config.cores} OMP_NUM_THREADS={config.cores} MKL_NUM_THREADS={config.cores}",
              # Restrict dense-matrix preflight to the allocation, not node physical RAM.
              f"export NADOC_HYDRO_MEM_GB={config.mem_gb * 1024**3 / 1e9 * 0.8:.6f}"]
    if config.arbd:
        lines.append(f"export PATH={q(str(Path(config.arbd).parent))}:$PATH")
    lines.append(f"{q(config.python)} -m backend.core.solver_cluster_worker {engine} {q(remote + '/workspace')} {q(job.job_id)}")
    return "\n".join(lines) + "\n"


async def preflight(conn, engine, config):
    if not conn.is_connected():
        raise RuntimeError("Reconnect to the selected provider in the Clusters card")
    imports = "import numpy, scipy, pydantic, numba, networkx, orjson, psutil, fastapi, sqlmodel, appdirs"
    if engine == "mrdna":
        imports += "; import mrdna"
    cmd = f"{shlex.quote(config.python)} -c {shlex.quote(imports)}"
    if engine == "mrdna":
        cmd += f" && test -x {shlex.quote(config.arbd)}"
        if Path(config.arbd).name != "arbd":
            raise ValueError("The remote ARBD executable must be named arbd")
    # Cold imports from a RunPod network volume can exceed 30 seconds even
    # when the managed environment is complete. Keep startup bounded while
    # allowing the shared filesystem to populate its cache.
    result = await conn.run(cmd, timeout=180)
    if result.rc:
        raise RuntimeError("Remote solver environment check failed. Configure a Python environment with NADOC dependencies"
                           + (" and mrDNA, plus an installed ARBD executable" if engine == "mrdna" else "")
                           + ": " + (result.stderr or result.stdout)[-1500:])


def bundle_inputs(path, engine, job, workspace):
    """Package current implementation plus existing derived simulation inputs, never author a design."""
    jd = job.job_dir(workspace)
    manifest = {}
    with tarfile.open(path, "w:gz", compresslevel=1) as archive:
        for source in (_ROOT / "backend").rglob("*"):
            runtime_file = (source.suffix == ".py"
                            or source.is_relative_to(_ROOT / "backend" / "data")
                            or source.is_relative_to(_ROOT / "backend" / "core" / "data")
                            or (source.parent == _ROOT / "backend" / "core" and source.suffix == ".txt"))
            if source.is_file() and not source.is_symlink() and "__pycache__" not in source.parts and runtime_file:
                manifest[str(source.relative_to(_ROOT))] = hashlib.sha256(source.read_bytes()).hexdigest()
                archive.add(source, arcname=str(source.relative_to(_ROOT)), recursive=False)
        for name in ("design.json", "job.json"):
            manifest[name] = hashlib.sha256((jd / name).read_bytes()).hexdigest()
            archive.add(jd / name, arcname=f"workspace/{engine}_jobs/{job.job_id}/{name}", recursive=False)
    (jd / "submission-manifest.json").write_text(json.dumps(manifest, indent=2))


async def submit(engine, job_id, workspace, conn):
    cls = job_class(engine)
    job = cls.load(job_id, workspace)
    config, profile, partition = validate_settings(engine, job.remote["settings"], workspace)
    await preflight(conn, engine, config)
    from backend.core.cluster_config import resolve_paths
    remote = resolve_paths(profile, conn.user, f"{engine}-{job_id}-{uuid.uuid4().hex[:8]}")["scratch_dir"]
    await conn.mkdir_p(remote)
    with tempfile.TemporaryDirectory(prefix="nadoc-solver-submit-") as tmp:
        archive = Path(tmp) / "inputs.tar.gz"
        bundle_inputs(archive, engine, job, workspace)
        await conn.sftp_put(str(archive), remote + "/inputs.tar.gz")
        sbatch = Path(tmp) / "submit.sbatch"
        sbatch.write_text(script(engine, job, remote, config, partition))
        await conn.sftp_put(str(sbatch), remote + "/submit.sbatch")
    q = shlex.quote
    extracted = await conn.run(f"cd {q(remote)} && tar --no-same-owner -xzf inputs.tar.gz", timeout=120)
    if extracted.rc:
        raise RuntimeError(extracted.stderr or "Remote input extraction failed")
    # Save durable intent BEFORE sbatch. An interrupted reply must never cause a duplicate submission.
    job.remote.update(directory=remote, scheduler_state="SUBMITTING", submission_uncertain=True)
    job.save(workspace)
    result = await conn.run(f"cd {q(remote)} && bash -o pipefail -c 'sbatch --parsable submit.sbatch | tee submission.id'", timeout=30)
    jid = result.stdout.strip().split(";")[0]
    if result.rc or not re.fullmatch(r"\d+", jid):
        # A pipeline failure can occur after sbatch accepted the job (for
        # example tee cannot write). Keep uncertainty until a receipt is found.
        raise RuntimeError(result.stderr or result.stdout or "No scheduler submission receipt")
    job.remote.update(slurm_job_id=jid, scheduler_state="PENDING", submission_uncertain=False)
    job.status = type(job.status)("queued")
    job.error = None
    job.save(workspace)


def _background(engine, job_id, workspace, action):
    key = (str(workspace), engine, job_id)
    with _LOCK:
        if key in _TASKS:
            return
        _TASKS.add(key)
    def work():
        from backend.core.alpine_worker import WorkerClient
        try:
            asyncio.run(action(engine, job_id, workspace, WorkerClient()))
        except Exception as exc:
            job = job_class(engine).load(job_id, workspace)
            job.remote["last_error"] = str(exc)
            if action is submit and not job.remote.get("submission_uncertain"):
                job.status = type(job.status)("failed")
                job.error = str(exc)
            job.save(workspace)
        finally:
            with _LOCK:
                _TASKS.discard(key)
                _LAST[key] = time.monotonic()
    threading.Thread(target=work, daemon=True, name=f"{engine}-alpine-{job_id}").start()


def start(job, workspace, engine):
    if job.remote.get("slurm_job_id") or job.remote.get("submission_uncertain"):
        raise ValueError("This remote job has a submission receipt or unresolved submission. Create a new job to rerun; it will start from the original snapshot.")
    validate_settings(engine, job.remote["settings"], workspace)
    job.status = type(job.status)("preparing")
    job.save(workspace)
    _background(engine, job.job_id, workspace, submit)


async def refresh(engine, job_id, workspace, conn):
    if not conn.is_connected():
        return
    cls = job_class(engine)
    job = cls.load(job_id, workspace)
    jid = job.remote.get("slurm_job_id")
    if not jid:
        if not job.remote.get("submission_uncertain"):
            return
        receipt = await conn.run(f"cat {shlex.quote(job.remote['directory'] + '/submission.id')}", timeout=20)
        jid = receipt.stdout.strip().split(";")[0]
        if receipt.rc or not re.fullmatch(r"\d+", jid):
            raise RuntimeError("Submission receipt unresolved. Inspect Alpine before retrying; no duplicate job will be submitted.")
        job.remote.update(slurm_job_id=jid, submission_uncertain=False)
        job.save(workspace)
    result = await conn.run(f"timeout 15s sacct -X -n -P -j {int(jid)} -o JobID,State,ExitCode", timeout=20)
    if result.rc:
        raise RuntimeError(result.stderr or "Scheduler query failed")
    row = next((r.split("|") for r in result.stdout.splitlines() if r.startswith(jid + "|")), None)
    if not row:
        return
    state = row[1].split()[0].rstrip("+")
    job.remote.update(scheduler_state=state, last_checked=time.time(), last_error=None)
    if state in _ACTIVE:
        job.status = type(job.status)("queued" if state == "PENDING" else "running")
        job.save(workspace)
        from backend.core.solver_progress import sync_remote_progress
        await sync_remote_progress(engine, job, workspace, conn)
        return
    await collect(engine, job, workspace, conn, state, row[2])


async def collect(engine, job, workspace, conn, state, exit_code):
    job_id = job.job_id
    job.remote["downloading"] = True
    job.save(workspace)
    remote = job.remote["directory"]
    q = shlex.quote
    # Transfer results into staging first. Never overwrite local provenance or job identity.
    relative = f"workspace/{engine}_jobs/{job_id}"
    # Multi-gigabyte native trajectories on network storage can take several
    # minutes to compress. The RunPod budget/watchdog still bounds paid lifetime.
    packed = await conn.run(f"cd {q(remote)} && tar czf results.tar.gz -C {q(relative)} .", timeout=900)
    if packed.rc:
        raise RuntimeError(packed.stderr or "Could not package solver results")
    with tempfile.TemporaryDirectory(prefix=".solver-results-", dir=job.job_dir(workspace)) as tmp:
        archive = Path(tmp) / "results.tar.gz"
        await conn.sftp_get(remote + "/results.tar.gz", str(archive))
        staging = Path(tmp) / "results"
        with tarfile.open(archive) as tar:
            members = tar.getmembers()
            if any(not (m.isfile() or m.isdir()) or Path(m.name).is_absolute() or ".." in Path(m.name).parts for m in members):
                raise ValueError("Unsafe remote result archive")
            required = sum(m.size for m in members) * 2
            if required > shutil.disk_usage(tmp).free:
                raise RuntimeError(f"Result collection needs {required / 1024**3:.1f} GiB free for staging and installation")
            tar.extractall(staging, filter="data")
        reported = json.loads((staging / "job.json").read_text())
        if reported.get("job_id") != job_id or reported.get("design_fingerprint") != job.design_fingerprint:
            raise ValueError("Remote result identity does not match submitted job")
        for source in staging.rglob("*"):
            if source.is_file() and source.name not in {"job.json", "design.json"} and not source.name.startswith(("runtime", ".")):
                target = job.job_dir(workspace) / source.relative_to(staging)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        # Copy only scientific result metadata. Keep all local ownership/path/submission fields.
        for field in ("sim_seconds", "n_nodes", "rmsf_min_nm", "rmsf_max_nm", "n_override", "n_beads", "execution"):
            if hasattr(job, field) and field in reported:
                setattr(job, field, reported[field])
        success = state == "COMPLETED" and exit_code == "0:0" and reported.get("status") == "completed" and (staging / "display.json").is_file()
        job.status = type(job.status)("completed" if success else "stopped" if state == "CANCELLED" else "failed")
        job.error = None if success else reported.get("error") or f"{job.execution_target} {state}. No completed result. A new run restarts from the original snapshot."
        for stage in job.stages:
            stage.status = "done" if success else "failed"
    try:
        await conn.sftp_get(remote + "/slurm.out", str(job.job_dir(workspace) / "alpine.log"))
    except Exception:
        pass  # result receipt is authoritative; a missing scheduler log is optional
    job.remote.update(downloading=False, results_collected=True)
    job.save(workspace)


def reconcile(job, workspace, engine):
    key = (str(workspace), engine, job.job_id)
    if (job.remote.get("slurm_job_id") or job.remote.get("submission_uncertain")) and not job.remote.get("results_collected") and time.monotonic() - _LAST.get(key, 0) > 30:
        _background(engine, job.job_id, workspace, refresh)
    elif not job.remote.get("slurm_job_id") and not job.remote.get("submission_uncertain") and job.status.value == "preparing":
        with _LOCK:
            active = key in _TASKS
        if not active:
            job.status = type(job.status)("failed")
            job.error = "Remote preparation was interrupted before submission. Retry this job."
            job.save(workspace)
    return job


async def cancel(job, workspace):
    from backend.core.alpine_worker import WorkerClient
    conn = WorkerClient()
    jid = job.remote.get("slurm_job_id")
    if not jid:
        raise ValueError("Submission has not returned a scheduler ID. Wait for its receipt before cancelling.")
    if not conn.is_connected():
        raise ValueError("Reconnect to Alpine to cancel this job")
    result = await conn.run(f"scancel {int(jid)}", timeout=20)
    if result.rc:
        raise ValueError(result.stderr or "Cancellation failed")
    job.remote["cancel_requested"] = True
    job.save(workspace)
    return {"ok": True, "status": "cancelling"}


def progress(job, workspace=None):
    if getattr(job, 'dynamics', False) and workspace is not None:
        from backend.core.solver_progress import dynamics_progress, load_receipt
        result = dynamics_progress(job, load_receipt(job.job_dir(workspace), remote=True), remote=True)
        provider = "RunPod" if job.execution_target == "runpod" else "Alpine"
        result['phase'] = f"{provider} · {result['phase']}"
        return result
    remote = job.remote
    phase = "Downloading results" if remote.get("downloading") else remote.get("scheduler_state", "Preparing remote submission")
    return {"status": job.status.value, "overall": 1.0 if job.status.value == "completed" else 0.0,
            "eta_seconds": None, "phase": f"{job.execution_target.title()} · {phase}", "remote": remote}


def error_log(job, workspace):
    """Bounded scheduler/native output for the existing error-log popup."""
    path = job.job_dir(workspace) / 'alpine.log'
    tail = ''
    if path.is_file():
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 65536))
            tail = stream.read(65536).decode('utf8', errors='replace')
    return '\n'.join(part for part in [job.error, tail] if part) or '(no error recorded)'
