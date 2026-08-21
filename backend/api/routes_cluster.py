"""API layer — compute-cluster connection endpoints (Alpine remote-execution, Phase 1).

Thin wiring over ``backend/core/cluster_ssh.py`` (live session) and
``backend/core/cluster_config.py`` (static profiles).  Holds no state itself.

Routes
------
  GET  /cluster/profiles          — available cluster profiles (no credentials)
  POST /cluster/connect           — authenticate (password + Duo) → status
  GET  /cluster/status            — current connection state
  POST /cluster/disconnect        — drop the live connection + clear creds
  GET  /cluster/availability      — live per-partition GPU availability + wait estimate

Mounted in ``backend/api/main.py`` via ``app.include_router(..., prefix="/api")``.
Note: distinct from ``routes_clusters.py`` (plural) which is deformation-cluster
editing — unrelated.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.assembly import _WORKSPACE_DIR
from backend.core import cluster_config, cluster_ssh

logger = logging.getLogger(__name__)

router = APIRouter()

# Strong references for post-authentication reconciliation tasks. Authentication and
# connection UI must not wait while a multi-GB remote job is inspected/downloaded.
_POST_CONNECT_TASKS: set[asyncio.Task] = set()


async def _reconcile_after_connect(mgr) -> None:
    """Best-effort remote-job reconciliation after the connect response is released."""
    from backend.core import alpine_operations

    op_id = alpine_operations.new_operation_id()
    started = time.monotonic()
    alpine_operations.event("post_connect_reconciliation_start", operation_id=op_id)
    try:
        from backend.core import md_executor  # noqa: PLC0415

        # Login is the recovery boundary for work that finished while NADOC had no
        # session. Besides ordinary queued/running records, audit a terminal record
        # whose prior result transfer was interrupted; the periodic supervisor keeps
        # its narrower active-only scan to avoid retrying a permanent file error forever.
        await md_executor.poll_remote_jobs(
            _WORKSPACE_DIR, conn=mgr, recover_incomplete=True
        )
    except asyncio.CancelledError:
        alpine_operations.finish(
            "post_connect_reconciliation", op_id, started, outcome="cancelled"
        )
        raise
    except Exception as exc:  # noqa: BLE001
        alpine_operations.finish(
            "post_connect_reconciliation", op_id, started,
            outcome="error", error=str(exc),
        )
        logger.exception("post-connect remote poll failed")
    else:
        alpine_operations.finish(
            "post_connect_reconciliation", op_id, started, outcome="success"
        )


def _start_post_connect_reconciliation(mgr) -> None:
    task = asyncio.create_task(_reconcile_after_connect(mgr))
    _POST_CONNECT_TASKS.add(task)
    task.add_done_callback(_POST_CONNECT_TASKS.discard)


class SlurmPreviewRequest(BaseModel):
    cluster_name: str = "alpine"
    partition: str | None = None  # None → auto-pick
    total_ns: float = 0.0
    n_atoms: int | None = None  # None → estimate from the active design
    job_name: str = "nadoc_job"
    safety_factor: float = 1.5


class ConnectRequest(BaseModel):
    cluster_name: str = "alpine"
    host: str | None = None  # defaults to the profile host
    user: str
    password: str
    duo_method: str = "push"  # "push" or a 6-digit passcode


@router.get("/cluster/profiles")
def list_profiles():
    profiles = cluster_config.load_profiles(_WORKSPACE_DIR)
    return {
        "profiles": [
            {
                "name": p.name,
                "host": p.host,
                "scheduler": p.scheduler,
                "default_partition": p.default_partition,
                "default_qos": p.default_qos,
            }
            for p in profiles.values()
        ]
    }


@router.get("/cluster/status")
def cluster_status():
    return cluster_ssh.get_manager().status()


@router.post("/cluster/connect")
async def cluster_connect(req: ConnectRequest):
    profiles = cluster_config.load_profiles(_WORKSPACE_DIR)
    profile = profiles.get(req.cluster_name)
    if profile is None:
        raise HTTPException(
            status_code=404, detail=f"unknown cluster '{req.cluster_name}'"
        )
    host = req.host or profile.host
    if not req.user or not req.password:
        raise HTTPException(status_code=400, detail="user and password are required")
    mgr = cluster_ssh.get_manager()
    try:
        await mgr.connect(host, req.user, req.password, req.duo_method)
    except cluster_ssh.ClusterSSHError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # Authentication is complete NOW. Return that authoritative state before reconciling
    # remote jobs: reconciliation may download/process VoltronCoreArm data for minutes, and
    # awaiting it left the login modal and every cluster consumer stuck on "connecting"
    # while the authenticated SSH connection was already moving bytes.
    connected_status = mgr.status()
    _start_post_connect_reconciliation(mgr)
    return connected_status


@router.post("/cluster/disconnect")
async def cluster_disconnect():
    mgr = cluster_ssh.get_manager()
    await mgr.disconnect()
    return mgr.status()


@router.get("/cluster/namd-modules")
async def cluster_namd_modules():
    """Live-list the NAMD modules on the cluster so the exact GPU (CUDA) vs CPU build
    name can be confirmed and set in ``gpu_module_loads`` (workspace/clusters.json)."""
    mgr = cluster_ssh.get_manager()
    if not mgr.is_connected():
        raise HTTPException(status_code=409, detail="not connected to a cluster")
    from backend.core import md_executor

    try:
        modules = await md_executor.list_namd_modules(conn=mgr)
    except cluster_ssh.ClusterSSHError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"modules": modules}


class NamdBuildRequest(BaseModel):
    cluster_name: str = "alpine"
    source_dir: str  # local NAMD source tree to ship
    name: str = "namd-git"  # build folder under <project>/nadoc_builds/
    modules: list[str] | None = None  # None → gcc/11.2.0 + cuda/12.1.1
    gencodes: list[str] | None = None  # None → sm_80/89/90 + compute_90 PTX
    cores: int = 8
    partition: str = "acpu"
    qos: str = "cpu-normal"
    walltime: str = "06:00:00"


@router.post("/cluster/build/namd")
async def cluster_build_namd(req: NamdBuildRequest):
    """Compile a CUDA / GPU-resident NAMD on the cluster as a batch job.

    Alpine has no CUDA NAMD module and cannot run a desktop-built binary (glibc
    2.28 vs 2.38), so this is the only route to GPU-resident there.  Packs the
    source, uploads it, and submits a generated build script; the build then runs
    unattended.  Returns as soon as SLURM accepts the job.

    Not a remote shell: the script is generated from a template and every parameter
    is validated, with writes confined to ``<project_base>/nadoc_builds/<name>``.
    """
    from backend.core import cluster_build  # noqa: PLC0415

    profiles = cluster_config.load_profiles(_WORKSPACE_DIR)
    profile = profiles.get(req.cluster_name)
    if profile is None:
        raise HTTPException(
            status_code=404, detail=f"unknown cluster '{req.cluster_name}'"
        )
    mgr = cluster_ssh.get_manager()
    if not mgr.is_connected():
        raise HTTPException(status_code=409, detail="not connected to a cluster")

    src = Path(req.source_dir).expanduser()
    if not src.is_dir():
        raise HTTPException(status_code=400, detail=f"source_dir not found: {src}")
    try:
        return await cluster_build.run_namd_build(
            mgr,
            profile,
            source_dir=src,
            name=req.name,
            modules=req.modules,
            gencodes=req.gencodes,
            cores=req.cores,
            partition=req.partition,
            qos=req.qos,
            walltime=req.walltime,
        )
    except ValueError as exc:  # a rejected module/gencode/name
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except cluster_ssh.ClusterSSHError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/cluster/build/namd")
async def cluster_build_namd_status(tail: int = 40):
    """Progress of the in-flight (or last) NAMD build, with the tail of its log."""
    from backend.core import cluster_build, cluster_queue  # noqa: PLC0415

    state = cluster_build.build_state()
    mgr = cluster_ssh.get_manager()
    jid = state.get("slurm_job_id")
    if jid and mgr.is_connected():
        try:
            res = await mgr.run(cluster_queue.probe_command("job", jid), timeout=30.0)
            for tok in (res.stdout or "").split():
                if tok.startswith("JobState="):
                    state["slurm_state"] = tok.split("=", 1)[1]
            log = state.get("log")
            if log:
                out = await mgr.run(
                    f"tail -n {max(1, min(int(tail), 400))} '{log}' 2>&1", timeout=30.0
                )
                state["log_tail"] = out.stdout or out.stderr
        except Exception:  # noqa: BLE001 — status must never fail the poll
            logger.exception("build status poll failed")
    return state


@router.get("/cluster/probe")
async def cluster_probe(name: str, arg: str | None = None):
    """Run one NAMED read-only probe on the cluster and return its raw output.

    Not a shell: ``name`` selects from a fixed registry in ``cluster_queue._PROBES``
    and ``arg`` is validated against a strict token pattern, so no caller-supplied
    string ever reaches a command line.  Every probe only reads state (``module
    spider``, ``ldd``, ``nvidia-smi``, ``squeue``, ``scontrol show``, ``sinfo``).

    Exists because diagnosing a cluster-side failure — an unknown module, a glibc
    floor, a job NADOC did not submit — otherwise required a code change per question.
    """
    from backend.core import cluster_queue  # noqa: PLC0415

    mgr = cluster_ssh.get_manager()
    if not mgr.is_connected():
        raise HTTPException(status_code=409, detail="not connected to a cluster")
    try:
        cmd = cluster_queue.probe_command(name, arg)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        res = await mgr.run(cmd, timeout=60.0)
    except cluster_ssh.ClusterSSHError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "probe": name,
        "arg": arg,
        "rc": res.rc,
        "stdout": res.stdout,
        "stderr": res.stderr,
    }


@router.post("/cluster/slurm-preview")
async def cluster_slurm_preview(req: SlurmPreviewRequest):
    """The exact SLURM request a job WOULD be submitted with — before it exists.

    Offline: no cluster session needed, nothing is submitted.  Drives the Job Wizard's
    plan step, so the whole sbatch story (partition, QoS, GRES, walltime, memory,
    modules, the NAMD invocation, SU cost) is inspectable while the run is still being
    designed rather than only in the submit-review card afterwards.

    ``n_atoms`` is estimated from the active design when not supplied.  That estimate
    builds the design's heavy-atom model, which is slow the first time (~26 s on a
    6-helix bundle) and memoised on the design fingerprint afterwards — so the caller
    should treat this as a background fill-in, not a blocking render.
    """
    from backend.core import cluster_resources, slurm_script  # noqa: PLC0415

    profiles = cluster_config.load_profiles(_WORKSPACE_DIR)
    profile = profiles.get(req.cluster_name)
    if profile is None:
        raise HTTPException(
            status_code=404, detail=f"unknown cluster '{req.cluster_name}'"
        )

    n_atoms, source = req.n_atoms, "provided"
    if not n_atoms:
        source = "estimated"
        try:
            from starlette.concurrency import run_in_threadpool  # noqa: PLC0415

            from backend.api import state as design_state  # noqa: PLC0415
            from backend.core.md_vram import estimate_profile_from_design  # noqa: PLC0415

            design = design_state.get_or_404()
            prof = await run_in_threadpool(estimate_profile_from_design, design)
            if prof:
                n_atoms = prof["dna_atoms"] + prof["full_water"] * 3 + prof["ion_atoms"]
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 — no design / un-buildable: fall through
            logger.exception("slurm-preview: atom estimate failed")
    if not n_atoms:
        # Without a size there is no honest walltime; say so rather than invent one.
        return {
            "sized": False,
            "reason": "No design loaded, so the system size is unknown.",
            "cluster_name": profile.name,
        }

    try:
        resources = cluster_resources.recommend(
            profile,
            n_atoms=int(n_atoms),
            total_ns=float(req.total_ns),
            safety_factor=req.safety_factor,
            partition=req.partition,
        )
    except ValueError as exc:  # unknown forced partition
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    header = slurm_script.preview_header(profile, resources, job_name=req.job_name)
    # The wizard's first step now edits these resources in place, so it needs the QoS
    # tiers valid for the resolved partition — same list, same shape, as the submit-review
    # card's dropdown gets from ``/md/jobs/{id}/remote-recommendation``.
    available_qos = [
        {"name": q.name, "max_walltime_h": q.max_walltime_h}
        for q in profile.qos_tiers_for_partition(resources.get("partition"))
    ]
    return {
        "sized": True,
        "cluster_name": profile.name,
        "n_atoms": int(n_atoms),
        "n_atoms_source": source,
        "total_ns": req.total_ns,
        "resources": resources,
        "available_qos": available_qos,
        **header,
    }


def _job_shape(job_id: str, profile) -> dict | None:
    """Turn a prepared MD job into the shape the availability probe needs.

    Reuses ``routes_md._size_prepared_job`` so the ``sbatch --test-only`` probe asks
    about the *real* job (its atom count, ns and resource request) rather than a
    generic placeholder.  ``None`` when the job is unknown or not prepared yet — the
    probe then falls back to a partition-only view.
    """
    from backend.api.routes_md import _load_job, _size_prepared_job  # noqa: PLC0415

    try:
        job = _load_job(job_id)
    except Exception:  # noqa: BLE001 — an unknown job just means "no job shape"
        return None
    sizing = _size_prepared_job(job, profile, 1.5)
    if sizing is None:
        return None
    res = sizing["resources"]
    return {
        "n_atoms": sizing["n_atoms"],
        "total_ns": sizing["total_ns"],
        "measured_ns_per_day": sizing["measured_ns_per_day"],
        "gpus": res.get("gpus", 1),
        "cores": res.get("cores", 8),
        "mem_gb": res.get("mem_gb", 32),
        "walltime": res.get("walltime", "24:00:00"),
        "qos": res.get("qos"),
    }


@router.get("/cluster/availability")
async def cluster_availability(
    cluster_name: str = "alpine",
    job_id: str | None = None,
    history_days: int = 30,
    force: bool = False,
):
    """Live GPU availability per partition, with a queue-wait estimate.

    Read-only throughout — ``scontrol``/``squeue``/``sacct`` plus ``sbatch
    --test-only``, which predicts a start time without ever queuing a job.  Pass
    ``job_id`` to shape the estimate around a specific prepared job; ``force=true``
    bypasses the 60 s probe cache (the popup's "Re-check" button).
    """
    profiles = cluster_config.load_profiles(_WORKSPACE_DIR)
    profile = profiles.get(cluster_name)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"unknown cluster '{cluster_name}'")
    mgr = cluster_ssh.get_manager()
    if not mgr.is_connected():
        raise HTTPException(status_code=409, detail="not connected to a cluster")
    from backend.core import cluster_queue, cluster_throughput  # noqa: PLC0415

    shape = _job_shape(job_id, profile) if job_id else None

    def _throughput_for(partition: str):
        """Learned ns/day for THIS partition, or None.  Per-partition on purpose —
        reusing one measured number across partitions makes every row report the
        same speed and cancels the comparison."""
        if not shape:
            return None
        return cluster_throughput.lookup_throughput(
            _WORKSPACE_DIR,
            cluster=profile.name,
            partition=partition,
            n_atoms=shape["n_atoms"],
        )

    try:
        return await cluster_queue.probe_availability(
            mgr,
            profile,
            job_shape=shape,
            throughput_for=_throughput_for,
            history_days=history_days,
            force=force,
        )
    except cluster_ssh.ClusterSSHError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
