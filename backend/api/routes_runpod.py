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
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.api import state as design_state
from backend.core import runpod_preflight
from backend.core.md_vram import estimate_profile_from_design
from backend.core.runpod_api import RunpodClient, RunpodError
from backend.core.runpod_script import (
    GPU_TYPES,
    plan_execution,
    required_vram_mb,
)
from backend.core.runpod_select import gpu_options as _rank_gpu_options, load_rate_registry

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
    #
    # OPTIONAL so the setup wizard can verify the key FIRST (which is what unlocks the
    # balance + volume-list lookups), then reconnect with the volume the user picked.
    network_volume_id: Optional[str] = None


@router.post("/runpod/connect")
async def connect(body: ConnectRequest):
    """Verify the key by listing pods, then hold it in memory."""
    client = RunpodClient(body.api_key)
    try:
        pods = await client.list_pods()
    except RunpodError as exc:
        await client.aclose()
        raise HTTPException(400, str(exc)) from exc

    # Don't drop a volume the user already chose on a key-only re-verify — but a fresh
    # volume in this request always wins.
    keep_volume = body.network_volume_id or _SESSION.network_volume_id
    await _SESSION.disconnect()
    _SESSION.client = client
    _SESSION.network_volume_id = keep_volume
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


@router.get("/runpod/balance")
async def balance():
    """The account balance — RunPod destroys every pod at $0. Shown in the setup wizard.

    Needs the key (held in memory after ``connect``). Never 500s: an unreadable balance is
    ``{"available": false, "reason": ...}`` so the wizard can warn rather than crash.
    """
    if not _SESSION.api_key:
        return {"available": False, "reason": "not connected — enter your API key first"}
    return await runpod_preflight.fetch_balance(_SESSION.api_key)


@router.get("/runpod/volumes")
async def volumes():
    """Every network volume on the account, for the wizard's volume dropdown.

    Read-only; creates no pod. The volume the user picks is the one carrying their patched
    NAMD — the wizard sends it back via ``connect`` to finalise the session.
    """
    vols = await _SESSION.require().list_network_volumes()
    return {"volumes": vols}


@router.get("/runpod/ssh-public-key")
def ssh_public_key():
    """The local SSH public key, for the user to paste into RunPod Settings → SSH Keys.

    RunPod injects account public keys into every pod at CREATION; a key added to a running
    pod dies with it. Without the matching key registered, pods boot and refuse every login.
    Returns ``present: false`` (not an error) when there is no local keypair, so the wizard
    can show the ``ssh-keygen -t ed25519`` hint.
    """
    pub = Path.home() / ".ssh" / "id_ed25519.pub"
    if not pub.exists():
        return {"present": False, "public_key": None}
    try:
        return {"present": True, "public_key": pub.read_text().strip()}
    except OSError as exc:
        logger.warning("runpod: could not read %s: %s", pub, exc)
        return {"present": False, "public_key": None}


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


class GpuOptionsRequest(BaseModel):
    n_atoms: Optional[int] = Field(
        None, gt=0, description="System size; if omitted, sized from the active design")


@router.post("/runpod/gpu-options")
async def gpu_options(body: GpuOptionsRequest | None = None):
    """Ranked list of currently-available GPUs for the active design's RELAXATION — each with
    live price, estimated wall-clock, and estimated cost. Fuses live RunPod stock/prices with the
    learned per-arch throughput (runpod_select). Creates no pod; feeds the cluster-card
    "Check RunPod GPUs" picker.
    """
    n_atoms = body.n_atoms if body else None
    if not n_atoms:
        try:
            design = design_state.get_or_404()
            profile = await run_in_threadpool(estimate_profile_from_design, design)
            if profile:
                n_atoms = profile["dna_atoms"] + profile["full_water"] * 3 + profile["ion_atoms"]
        except Exception:  # noqa: BLE001 — no design / sizing failure => soft "load a design"
            logger.warning("runpod gpu-options: could not size active design", exc_info=True)
    if not n_atoms:
        return {"ok": False, "gpus": [], "n_atoms": None, "connected": _SESSION.is_connected(),
                "note": "Load a design first — couldn't size the system."}

    stock = None
    if _SESSION.is_connected() and _SESSION.api_key:
        try:
            stock = await runpod_preflight.fetch_gpu_stock(_SESSION.api_key)
        except Exception:  # noqa: BLE001 — a stock failure means indicative prices, not a 500
            logger.warning("runpod gpu-options: GPU stock lookup failed", exc_info=True)

    rows = _rank_gpu_options(n_atoms, build="release", stock=stock, registry=load_rate_registry())
    return {
        "ok": True,
        "n_atoms": n_atoms,
        "relax_ns": 19.2,
        "connected": _SESSION.is_connected(),
        "gpus": rows,
        "note": (None if stock else
                 "Prices/availability indicative — connect RunPod for live stock."),
    }


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
