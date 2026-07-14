"""API layer — RunPod remote-execution endpoints.

Thin wiring over ``backend/core/runpod_api.py`` (REST client) and
``backend/core/runpod_executor.py`` (provision → run → fetch → destroy). Holds only the
live session, exactly like ``routes_cluster`` does for Alpine.

Routes
------
  POST /runpod/connect        — hold an API key in memory + verify it, list volumes
  GET  /runpod/status         — connected? which volume? any live pods?
  POST /runpod/disconnect     — drop the key and close the client
  GET  /runpod/pods           — live pods (the leak check: anything here is BILLING)
  POST /runpod/pods/{id}/terminate — manual kill switch
  POST /runpod/estimate       — GPU + cost estimate for a system size (no pod created)

⚠️ **The API key is held in memory only, never written to disk** — the same rule as the
Alpine credentials in ``cluster_ssh``. Unlike Alpine there is no Duo, so re-entering it
after a server restart needs no human ceremony.

Mounted in ``backend/api/main.py`` via ``app.include_router(..., prefix="/api")``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core import runpod_preflight
from backend.core.runpod_api import RunpodClient, RunpodError
from backend.core.runpod_script import (
    GPU_TYPES,
    plan_execution,
    required_vram_mb,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class _Session:
    """The live RunPod session. Key in memory only; never persisted."""

    def __init__(self) -> None:
        self.client: Optional[RunpodClient] = None
        self.network_volume_id: Optional[str] = None
        # Kept ONLY to query GPU stock over GraphQL (the REST API exposes no availability
        # endpoint). In memory, never persisted — same rule as the Alpine credentials.
        self.api_key: Optional[str] = None

    def is_connected(self) -> bool:
        return self.client is not None

    def require(self) -> RunpodClient:
        if self.client is None:
            raise HTTPException(400, "Not connected to RunPod. Enter an API key first.")
        return self.client

    async def disconnect(self) -> None:
        if self.client is not None:
            await self.client.aclose()
        self.client = None
        self.api_key = None


_SESSION = _Session()


class ConnectRequest(BaseModel):
    api_key: str = Field(..., min_length=8)
    # The volume carrying the patched NAMD + packages + checkpoints. A pod without it
    # is an empty box that would have to rebuild NAMD from source.
    network_volume_id: str


@router.post("/runpod/connect")
async def connect(body: ConnectRequest):
    """Verify the key by listing pods, then hold it in memory."""
    client = RunpodClient(body.api_key)
    try:
        pods = await client.list_pods()
    except RunpodError as exc:
        await client.aclose()
        raise HTTPException(400, str(exc)) from exc

    await _SESSION.disconnect()
    _SESSION.client = client
    _SESSION.network_volume_id = body.network_volume_id
    _SESSION.api_key = body.api_key
    logger.info("runpod: connected (%d live pods)", len(pods))

    # ── REAP ORPHANS ─────────────────────────────────────────────────────────
    # The API key is held in MEMORY ONLY, so after a backend crash / dev-server reload
    # NADOC has no key and literally CANNOT terminate a pod it left running — the
    # earliest possible moment to clean up is the instant you reconnect. A pod that
    # outlived its NADOC process is billing with nothing watching it.
    #
    # Only pods named `nadoc-*` are touched, so a pod you started by hand is safe.
    from backend.core import runpod_supervisor

    reaped = await runpod_supervisor.reap_orphan_pods(client)
    if reaped:
        logger.warning("runpod: reaped %d orphaned pod(s): %s", len(reaped), reaped)

    payload = _status_payload(live_pods=max(0, len(pods) - len(reaped)))
    payload["reaped_pods"] = reaped
    return payload


@router.get("/runpod/status")
async def status():
    if not _SESSION.is_connected():
        return _status_payload()
    try:
        pods = await _SESSION.require().list_pods()
    except RunpodError:
        return _status_payload()
    return _status_payload(live_pods=len(pods))


@router.post("/runpod/disconnect")
async def disconnect():
    await _SESSION.disconnect()
    return _status_payload()


@router.get("/runpod/pods")
async def list_pods():
    """Every live pod. **Anything in this list is billing right now.**

    This is the leak check: a bug that loses a pod id shows up here as a pod nobody
    remembers starting. The UI surfaces it with a terminate button for exactly that
    reason.
    """
    pods = await _SESSION.require().list_pods()
    return {
        "pods": [
            {
                "id": p.id,
                "status": p.desired_status,
                "cost_per_hr": p.cost_per_hr,
                "ssh": (
                    f"{p.public_ip}:{p.ssh_port}" if p.public_ip and p.ssh_port else None
                ),
            }
            for p in pods
        ]
    }


@router.post("/runpod/pods/{pod_id}/terminate")
async def terminate(pod_id: str):
    """Manual kill switch. Idempotent — terminating a dead pod is not an error."""
    await _SESSION.require().terminate_pod(pod_id)
    logger.info("runpod: terminated pod %s", pod_id)
    return {"ok": True, "pod_id": pod_id}


class EstimateRequest(BaseModel):
    n_atoms: int = Field(..., gt=0)


@router.post("/runpod/estimate")
def estimate(body: EstimateRequest):
    """Which GPU would this system need, and what would it cost? Creates no pod.

    Sizing comes from the VRAM model MEASURED on a rented 4090 across systems spanning
    25x (225k → 5.66M atoms): offload ≈ 2.1 GB/Matom, resident ≈ 3.2 GB/Matom.
    """
    plan = plan_execution(body.n_atoms)
    gpu = plan["gpu"]
    return {
        "n_atoms": body.n_atoms,
        "gpu": None if gpu is None else {
            "key": gpu.key,
            "label": gpu.label,
            "vram_mb": gpu.vram_mb,
            "usd_per_hour": gpu.usd_per_hour,
        },
        "gpu_resident": plan["gpu_resident"],
        "required_vram_mb": round(
            required_vram_mb(body.n_atoms, gpu_resident=plan["gpu_resident"])
        ),
        "reason": plan["reason"],
        "feasible": gpu is not None,
    }


class PreflightRequest(BaseModel):
    n_atoms: Optional[int] = Field(None, gt=0, description="Size the job too, if known")


@router.post("/runpod/preflight")
async def preflight(body: PreflightRequest | None = None):
    """Can a job actually run on RunPod right now? Answer BEFORE renting anything.

    Every check here corresponds to a failure that already happened on a real, billing
    pod. The UI blocks submission until they all pass.
    """
    stock = None
    if _SESSION.is_connected() and _SESSION.api_key:
        try:
            stock = await runpod_preflight.fetch_gpu_stock(_SESSION.api_key)
        except Exception:  # noqa: BLE001 — a stock lookup failure is a FAILED check, not a 500
            logger.warning("runpod: GPU stock lookup failed", exc_info=True)

    pre = runpod_preflight.evaluate(
        connected=_SESSION.is_connected(),
        network_volume_id=_SESSION.network_volume_id,
        ssh_key_present=_ssh_key_present(),
        stock=stock,
        n_atoms=(body.n_atoms if body else None),
    )
    return pre.to_dict()


def _ssh_key_present() -> bool:
    return (Path.home() / ".ssh" / "id_ed25519").exists()


@router.get("/runpod/gpu-types")
def gpu_types():
    return {
        "gpus": [
            {"key": g.key, "label": g.label, "vram_mb": g.vram_mb,
             "usd_per_hour": g.usd_per_hour}
            for g in GPU_TYPES
        ]
    }


def _status_payload(live_pods: int = 0) -> dict:
    return {
        "connected": _SESSION.is_connected(),
        "network_volume_id": _SESSION.network_volume_id,
        "live_pods": live_pods,
    }
