"""API layer — compute-cluster connection endpoints (Alpine remote-execution, Phase 1).

Thin wiring over ``backend/core/cluster_ssh.py`` (live session) and
``backend/core/cluster_config.py`` (static profiles).  Holds no state itself.

Routes
------
  GET  /cluster/profiles          — available cluster profiles (no credentials)
  POST /cluster/connect           — authenticate (password + Duo) → status
  GET  /cluster/status            — current connection state
  POST /cluster/disconnect        — drop the live connection + clear creds

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
