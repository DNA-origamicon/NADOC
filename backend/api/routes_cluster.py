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

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.assembly import _WORKSPACE_DIR
from backend.core import cluster_config, cluster_ssh

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectRequest(BaseModel):
    cluster_name: str = "alpine"
    host: str | None = None            # defaults to the profile host
    user: str
    password: str
    duo_method: str = "push"           # "push" or a 6-digit passcode


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
        raise HTTPException(status_code=404, detail=f"unknown cluster '{req.cluster_name}'")
    host = req.host or profile.host
    if not req.user or not req.password:
        raise HTTPException(status_code=400, detail="user and password are required")
    mgr = cluster_ssh.get_manager()
    try:
        await mgr.connect(host, req.user, req.password, req.duo_method)
    except cluster_ssh.ClusterSSHError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # Just reconnected — immediately reconcile in-flight remote jobs so a run that FINISHED
    # while the session was down gets its results fetched now (not up to ~30 s later when the
    # supervisor next runs), and any deferred scancel (a Stop issued while disconnected) is
    # drained.  Best-effort: a poll hiccup must never fail the connect.
    try:
        from backend.core import md_executor  # noqa: PLC0415
        await md_executor.poll_remote_jobs(_WORKSPACE_DIR, conn=mgr)
    except Exception:  # noqa: BLE001
        logger.exception("post-connect remote poll failed")
    return mgr.status()


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
            _WORKSPACE_DIR, cluster=profile.name,
            partition=partition, n_atoms=shape["n_atoms"],
        )

    try:
        return await cluster_queue.probe_availability(
            mgr, profile, job_shape=shape, throughput_for=_throughput_for,
            history_days=history_days, force=force,
        )
    except cluster_ssh.ClusterSSHError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
