"""API layer — RunPod remote-execution endpoints.

Thin wiring over ``backend/core/runpod_api.py`` (REST client) and
``backend/core/runpod_executor.py`` (provision → run → fetch → destroy). Holds only the
live session, exactly like ``routes_cluster`` does for Alpine.

Routes
------
  POST /runpod/connect        — hold an API key in memory + verify it, list volumes
  GET  /runpod/status         — connected? which volume? any live pods?
  POST /runpod/disconnect     — drop the key and close the client
  POST /runpod/volume         — set the session's network volume (no API key needed)
  GET  /runpod/pods           — live pods (the leak check: anything here is BILLING)
  POST /runpod/pods/{id}/terminate — manual kill switch
  POST /runpod/estimate       — GPU + cost estimate for a system size (no pod created)
  POST /runpod/gpu-options    — ranked cards for a RELAXATION ladder (Clusters-card picker)
  POST /runpod/job-preview    — ranked cards + storage + budget for a WHOLE plan (Job Wizard)

**The API key is read at startup from ``$RUNPOD_API_KEY`` or ``~/.runpod_key``**
(``runpod_api.resolve_api_key``) and the session connects itself — see ``autoconnect``.
Pasting a key into the setup wizard still works and overrides whatever was resolved.

This deliberately does NOT follow the Alpine rule in ``cluster_ssh``. Alpine takes a human
password plus a Duo push — a credential that cannot be stored. A RunPod API key is a machine
credential meant to be stored, and keeping it in memory only meant that after any restart
NADOC could not terminate a pod it was still being billed for.

Mounted in ``backend/api/main.py`` via ``app.include_router(..., prefix="/api")``.
"""

from __future__ import annotations

import logging
import os
from functools import partial
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.api import state as design_state
from backend.core import runpod_api, runpod_preflight
from backend.core.md_vram import estimate_profile_from_design
from backend.core.runpod_api import RunpodClient, RunpodError
from backend.core.runpod_script import (
    DEFAULT_BUDGET_USD,
    GPU_TYPES,
    plan_execution,
    required_vram_mb,
)
from backend.core.runpod_select import (
    gpu_options as _rank_gpu_options,
    load_rate_registry,
    plan_options,
)
from backend.core.runpod_storage import storage_estimate

logger = logging.getLogger(__name__)

router = APIRouter()


class _Session:
    """The live RunPod session — the client, its key, and the chosen volume."""

    def __init__(self) -> None:
        self.client: Optional[RunpodClient] = None
        self.network_volume_id: Optional[str] = None
        # Also kept to query GPU stock over GraphQL (the REST API exposes no availability
        # endpoint) and to read the balance, neither of which the client covers.
        self.api_key: Optional[str] = None
        # "env" | "file" | "manual" | "none" — surfaced in /runpod/status so the UI can say
        # WHY it is already connected instead of looking like it remembered a secret.
        self.key_source: str = "none"
        self.connection_error: Optional[str] = None

    def is_connected(self) -> bool:
        return self.client is not None

    def require(self) -> RunpodClient:
        if self.client is None:
            raise HTTPException(400, "Not connected to RunPod. Enter an API key first.")
        return self.client

    async def disconnect(self) -> None:
        if self.client is not None:
            # A supervisor keeps this exact client instance while a detached chain runs.
            # Closing it during a UI reconnect/disconnect turns a harmless controller
            # event into a polling failure. The task owns the retired instance until it
            # finishes; provider terminateAfter bounds the bill if NADOC never returns.
            from backend.core import runpod_supervisor

            if not runpod_supervisor.running_job_ids():
                await self.client.aclose()
            else:
                logger.info(
                    "runpod: retiring session client without closing it; %d supervised "
                    "job(s) still use it",
                    len(runpod_supervisor.running_job_ids()),
                )
        self.client = None
        self.api_key = None
        self.key_source = "none"
        self.connection_error = None


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
    """Verify a pasted key by listing pods, then make it the session's key.

    A key typed here always wins over the one ``autoconnect`` resolved at startup — that
    is how you use a second account without editing files.
    """
    client = RunpodClient(body.api_key)
    try:
        pods = await client.list_pods()
    except RunpodError as exc:
        await client.aclose()
        raise HTTPException(400, str(exc)) from exc
    return await _adopt(
        client,
        body.api_key,
        key_source="manual",
        network_volume_id=body.network_volume_id,
        live_pods=pods,
    )


async def _adopt(
    client: RunpodClient,
    api_key: str,
    *,
    key_source: str,
    network_volume_id: Optional[str],
    live_pods: list,
) -> dict:
    """Install an ALREADY-VERIFIED client as the session, then reap orphans + adopt jobs.

    Shared by ``connect`` (a pasted key) and ``autoconnect`` (the stored one) so both paths
    do the pod bookkeeping identically — a startup that connected but skipped the reap would
    leave exactly the billing pods this whole mechanism exists to catch.
    """
    # Don't drop a volume the user already chose on a key-only re-verify — but a fresh
    # volume in this request always wins.
    keep_volume = network_volume_id or _SESSION.network_volume_id
    await _SESSION.disconnect()
    _SESSION.client = client
    _SESSION.network_volume_id = keep_volume
    _SESSION.api_key = api_key
    _SESSION.key_source = key_source
    _SESSION.connection_error = None
    logger.info("runpod: connected via %s (%d live pods)", key_source, len(live_pods))

    # ── REAP ORPHANS ─────────────────────────────────────────────────────────
    # A pod that outlived its NADOC process is billing with nothing watching it. Startup
    # now resolves the key on its own, so this runs without waiting for a human to notice
    # and reconnect — which is the entire reason the key moved to disk.
    #
    # Only pods named `nadoc-*` are touched, so a pod you started by hand is safe.
    # Lazy: routes_md imports THIS module inside its own handlers, so a module-level
    # import either way would be a cycle.
    from backend.api.routes_md import _runpod_client_keys, _workspace
    from backend.core import runpod_supervisor

    reaped, adoptable = await runpod_supervisor.reap_orphan_pods(client, _workspace())
    if reaped:
        logger.warning("runpod: reaped %d orphaned pod(s): %s", len(reaped), reaped)

    # ── RE-ATTACH ────────────────────────────────────────────────────────────
    # A pod a still-running job claims is not an orphan — it is a run whose supervisor
    # died (a dev-server reload, a crash). NAMD is detached and carried on regardless;
    # what it lost is the only thing that polls it and the only thing that will ever
    # destroy the pod. Adopting restores both, and is why the shutdown hook is allowed
    # to leave pods up across a reload.
    adopted: list[str] = []
    for job in adoptable:
        try:
            runpod_supervisor.reattach_job(
                job,
                _workspace(),
                client=client,
                client_keys=_runpod_client_keys(),
                network_volume_id=keep_volume,
            )
            adopted.append(job.job_id)
        except Exception:  # noqa: BLE001 — one bad job must not block the connect
            logger.exception("runpod: could not re-attach job %s", job.job_id)
    if adopted:
        logger.warning(
            "runpod: re-attached %d in-flight job(s): %s", len(adopted), adopted
        )

    # A pod can disappear while NADOC itself is down (spot reclaim, host loss, account
    # interruption).  Such a job is neither adoptable nor an orphan, so the old startup
    # pass simply overlooked it and left the durable record "running" forever.  Relaunch
    # it from the network-volume checkpoint.  Explicit Stop and terminal states are
    # excluded; maximum-lifetime jobs are already PAUSED and require fresh spend consent.
    live_ids = {p.id for p in live_pods if not p.is_destroyed}
    restarted: list[str] = []
    from backend.core.md_job import MdJob, MdStatus

    for job in MdJob.list_jobs(_workspace()):
        if (
            job.execution_target == "runpod"
            and job.status == MdStatus.running
            and not job.user_stopped
            and job.runpod_pod_id not in live_ids
        ):
            volume_id = job.runpod_volume_id or keep_volume
            if not volume_id:
                logger.error(
                    "runpod: cannot auto-restart disrupted job %s: no network volume",
                    job.job_id,
                )
                continue
            job.status = MdStatus.paused
            job.resumable = True
            job.error = (
                "Pod disappeared while NADOC was offline; automatically restarting."
            )
            job.runpod_pod_id = None
            job.runpod_pid = None
            job.save(_workspace())
            runpod_supervisor.start_job(
                job,
                _workspace(),
                client=client,
                network_volume_id=volume_id,
                client_keys=_runpod_client_keys(),
            )
            restarted.append(job.job_id)

    payload = _status_payload(live_pods=max(0, len(live_pods) - len(reaped)))
    payload["reaped_pods"] = reaped
    payload["adopted_jobs"] = adopted
    payload["restarted_jobs"] = restarted
    return payload


async def autoconnect() -> Optional[dict]:
    """Connect from the stored key at server startup. Returns ``None`` if there isn't one.

    Called from ``main.lifespan``. Never raises and never blocks the server coming up: a
    RunPod outage, an expired key or no key at all must all leave NADOC perfectly usable
    for everything that is not a rented GPU.
    """
    if os.environ.get("NADOC_RUNPOD_AUTOCONNECT", "1") == "0":
        return None
    resolved = runpod_api.resolve_api_key()
    api_key, source = resolved.value, resolved.source
    if not api_key:
        logger.info(
            "runpod: no stored key ($%s or %s) — connect from the setup wizard",
            runpod_api.ENV_VAR,
            runpod_api.KEY_FILE,
        )
        return None

    client = RunpodClient(api_key)
    try:
        pods = await client.list_pods()
    except Exception as exc:  # noqa: BLE001 — startup must not fail on a RunPod outage
        await client.aclose()
        _SESSION.key_source = source
        _SESSION.connection_error = str(exc)
        logger.warning("runpod: stored key did not connect (%s): %s", source, exc)
        return None

    payload = await _adopt(
        client, api_key, key_source=source, network_volume_id=None, live_pods=pods
    )
    await _autopick_volume(client)
    payload["network_volume_id"] = _SESSION.network_volume_id
    return payload


async def _autopick_volume(client: RunpodClient) -> None:
    """Restore the network volume too, or a self-connected session is still unusable.

    The volume carries the patched NAMD; without one the pre-flight volume gate fails and
    the user has to open the wizard anyway — which would defeat the point of autoconnect.
    ``$RUNPOD_NETWORK_VOLUME_ID`` wins; otherwise adopt the account's volume only when there
    is exactly ONE, since any guess between several could stage a job onto the wrong disk.
    """
    if _SESSION.network_volume_id:
        return
    pinned = (os.environ.get("RUNPOD_NETWORK_VOLUME_ID") or "").strip()
    if pinned:
        _SESSION.network_volume_id = pinned
        logger.info("runpod: network volume %s (from env)", pinned)
        return
    try:
        vols = await client.list_network_volumes()
    except Exception:  # noqa: BLE001 — no volume is a degraded session, not a failed one
        logger.warning("runpod: volume lookup failed on autoconnect", exc_info=True)
        return
    if len(vols) == 1:
        _SESSION.network_volume_id = vols[0].get("id")
        logger.info(
            "runpod: network volume %s (the account's only one)",
            _SESSION.network_volume_id,
        )
    elif len(vols) > 1:
        logger.info(
            "runpod: %d network volumes — pick one in the setup wizard, or set "
            "$RUNPOD_NETWORK_VOLUME_ID",
            len(vols),
        )


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
        return {
            "available": False,
            "reason": "not connected — enter your API key first",
        }
    return await runpod_preflight.fetch_balance(_SESSION.api_key)


@router.get("/runpod/volumes")
async def volumes():
    """Every network volume on the account, for the wizard's volume dropdown.

    Read-only; creates no pod. The volume the user picks is the one carrying their patched
    NAMD — the wizard sends it back via ``connect`` to finalise the session.
    """
    vols = await _SESSION.require().list_network_volumes()
    return {"volumes": vols}


class VolumeRequest(BaseModel):
    network_volume_id: str = Field(..., min_length=1)


@router.post("/runpod/volume")
async def set_volume(body: VolumeRequest):
    """Point the live session at a network volume — **without needing the API key.**

    The setup modal can re-POST ``/runpod/connect`` to change the volume because it still
    holds the key in its own closure. The Job Wizard does not and must not handle the key at
    all, so without this it had no way to record a volume choice.

    Setting the session id is what makes the ``volume`` pre-flight check pass, so this has to
    take effect immediately rather than waiting for launch.
    """
    _SESSION.require()
    _SESSION.network_volume_id = body.network_volume_id
    logger.info("runpod: network volume set to %s", body.network_volume_id)
    return _status_payload()


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
                    f"{p.public_ip}:{p.ssh_port}"
                    if p.public_ip and p.ssh_port
                    else None
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
        "gpu": None
        if gpu is None
        else {
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
        None, gt=0, description="System size; if omitted, sized from the active design"
    )


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
                n_atoms = (
                    profile["dna_atoms"]
                    + profile["full_water"] * 3
                    + profile["ion_atoms"]
                )
        except Exception:  # noqa: BLE001 — no design / sizing failure => soft "load a design"
            logger.warning(
                "runpod gpu-options: could not size active design", exc_info=True
            )
    if not n_atoms:
        return {
            "ok": False,
            "gpus": [],
            "n_atoms": None,
            "connected": _SESSION.is_connected(),
            "note": "Load a design first — couldn't size the system.",
        }

    stock = None
    if _SESSION.is_connected() and _SESSION.api_key:
        try:
            stock = await runpod_preflight.fetch_gpu_stock(_SESSION.api_key)
        except Exception:  # noqa: BLE001 — a stock failure means indicative prices, not a 500
            logger.warning("runpod gpu-options: GPU stock lookup failed", exc_info=True)

    rows = _rank_gpu_options(
        n_atoms, build="release", stock=stock, registry=load_rate_registry()
    )
    return {
        "ok": True,
        "n_atoms": n_atoms,
        "relax_ns": 19.2,
        "connected": _SESSION.is_connected(),
        "gpus": rows,
        "note": (
            None
            if stock
            else "Prices/availability indicative — connect RunPod for live stock."
        ),
    }


class JobPreviewStage(BaseModel):
    """One planned NAMD stage, as the Job Wizard's plan table already describes it."""

    steps: int = Field(0, ge=0)
    dcd_freq: int = Field(1, ge=1)


class JobPreviewRequest(BaseModel):
    """Everything the wizard knows about a run that does not exist yet.

    Deliberately all-optional-with-defaults: the wizard calls this on every debounced plan
    refresh, including before a design is loaded, and a validation error there would be a dead
    panel rather than a "load a design" message.
    """

    n_atoms: Optional[int] = Field(
        None, gt=0, description="Sized from the active design if omitted"
    )
    relax_ns: float = Field(0.0, ge=0)
    production_ns: float = Field(0.0, ge=0)
    relax_timestep_fs: float = Field(4.0, gt=0)
    production_timestep_fs: float = Field(4.0, gt=0)
    stages: Optional[list[JobPreviewStage]] = Field(
        None, description="For the disk forecast. Omitted → no output-size estimate."
    )
    package_bytes: int = Field(0, ge=0)
    budget_usd: float = Field(DEFAULT_BUDGET_USD, gt=0)
    padding_nm: Optional[float] = Field(
        None,
        gt=0,
        description="Solvation padding, so the atom estimate follows the wizard's "
        "solvent settings. Omitted → the estimator's own default.",
    )
    build: str = Field(
        "release", description="NAMD build whose arch set gates the card list"
    )


@router.post("/runpod/job-preview")
async def job_preview(body: JobPreviewRequest | None = None):
    """What would this WHOLE plan cost and take on RunPod, and does it fit? Creates no pod.

    The Job Wizard's RunPod counterpart to ``/cluster/slurm-preview``. Unlike
    ``/runpod/gpu-options`` — which answers the narrower "what would a relaxation ladder cost"
    for the Clusters card — this takes the run the user is actually designing: its real ladder
    length, its real production length, and the timestep of each, all of which move while they
    are still on a later tab.

    Never raises on a missing session: a disconnected user still gets the ranked card list at
    indicative prices, because seeing roughly what a run costs is the whole point of asking
    before renting.
    """
    body = body or JobPreviewRequest()

    n_atoms, source = body.n_atoms, "provided"
    if not n_atoms:
        source = "estimated"
        try:
            design = design_state.get_or_404()
            kwargs = {"padding_nm": body.padding_nm} if body.padding_nm else {}
            profile = await run_in_threadpool(
                partial(estimate_profile_from_design, design, **kwargs)
            )
            if profile:
                n_atoms = (
                    profile["dna_atoms"]
                    + profile["full_water"] * 3
                    + profile["ion_atoms"]
                )
        except Exception:  # noqa: BLE001 — includes get_or_404's HTTPException, deliberately
            # The wizard re-asks this on EVERY debounced plan refresh, including before a
            # design is open. Letting `get_or_404` propagate would turn "you haven't loaded a
            # design yet" into an error toast on a panel the user is still filling in, so an
            # unsizable request is answered softly below — the same contract
            # ``/runpod/gpu-options`` already has.
            logger.warning(
                "runpod job-preview: could not size the active design", exc_info=True
            )
    if not n_atoms:
        # Without a size there is no honest cost. Say so rather than invent one.
        return {
            "sized": False,
            "connected": _SESSION.is_connected(),
            "reason": "No design loaded, so the system size is unknown.",
        }

    stock = None
    if _SESSION.is_connected() and _SESSION.api_key:
        try:
            stock = await runpod_preflight.fetch_gpu_stock(_SESSION.api_key)
        except Exception:  # noqa: BLE001 — a stock failure means indicative prices, not a 500
            logger.warning("runpod job-preview: GPU stock lookup failed", exc_info=True)

    try:
        gpus = plan_options(
            int(n_atoms),
            relax_ns=body.relax_ns,
            production_ns=body.production_ns,
            build=body.build,
            relax_timestep_fs=body.relax_timestep_fs,
            production_timestep_fs=body.production_timestep_fs,
            stock=stock,
            registry=load_rate_registry(),
        )
    except ValueError as exc:  # unknown build
        raise HTTPException(400, str(exc)) from exc

    # Storage and staging are quoted against the card the user would get FIRST, since that is
    # the one whose hourly rate the staging upload bills at.
    top = gpus[0] if gpus else None
    volume = await _volume_info(_SESSION.network_volume_id)
    storage = storage_estimate(
        stages=[(s.steps, s.dcd_freq) for s in (body.stages or [])],
        n_atoms=int(n_atoms),
        package_bytes=body.package_bytes,
        volume_size_gb=(volume or {}).get("size_gb"),
        usd_per_hour=(top or {}).get("usd_per_hour"),
    )

    balance = {"available": False, "reason": "not connected"}
    live_pods: list[dict] = []
    if _SESSION.api_key:
        balance = await runpod_preflight.fetch_balance(_SESSION.api_key)
    if _SESSION.is_connected():
        try:
            live_pods = [
                {"id": p.id, "status": p.desired_status, "cost_per_hr": p.cost_per_hr}
                for p in await _SESSION.require().list_pods()
            ]
        except Exception:  # noqa: BLE001 — a leak check that 500s is worse than one that is blank
            logger.warning("runpod job-preview: pod list failed", exc_info=True)

    pre = runpod_preflight.evaluate(
        connected=_SESSION.is_connected(),
        network_volume_id=_SESSION.network_volume_id,
        ssh_key_present=_ssh_key_present(),
        stock=stock,
        n_atoms=int(n_atoms),
    )

    estimated = (top or {}).get("total_cost")
    # The staging upload bills before NAMD starts a step, so it belongs INSIDE the budget
    # comparison — leaving it out is how a "just under budget" run goes over.
    staging_usd = storage["staging"].get("usd") or 0.0
    projected = (estimated + staging_usd) if estimated is not None else None

    return {
        "sized": True,
        "connected": _SESSION.is_connected(),
        "n_atoms": int(n_atoms),
        "n_atoms_source": source,
        "relax_ns": body.relax_ns,
        "production_ns": body.production_ns,
        "gpus": gpus,
        "storage": storage,
        "volume": volume,
        "balance": balance,
        "live_pods": live_pods,
        "preflight": pre.to_dict(),
        "budget": {
            "budget_usd": body.budget_usd,
            "estimated_usd": None if projected is None else round(projected, 2),
            "over_budget": bool(projected is not None and projected > body.budget_usd),
        },
        "note": (
            None
            if stock
            else "Prices and availability are indicative — connect RunPod for live stock."
        ),
    }


async def _volume_info(volume_id: Optional[str]) -> Optional[dict]:
    """The chosen network volume's row, or ``None``. Never raises — the storage forecast
    degrades to "size unknown" rather than taking the whole preview down with it."""
    if not volume_id or not _SESSION.is_connected():
        return None
    try:
        vols = await _SESSION.require().list_network_volumes()
    except Exception:  # noqa: BLE001
        logger.warning("runpod job-preview: volume lookup failed", exc_info=True)
        return None
    return next((v for v in vols if v.get("id") == volume_id), None)


def _ssh_key_present() -> bool:
    return (Path.home() / ".ssh" / "id_ed25519").exists()


@router.get("/runpod/gpu-types")
def gpu_types():
    return {
        "gpus": [
            {
                "key": g.key,
                "label": g.label,
                "vram_mb": g.vram_mb,
                "usd_per_hour": g.usd_per_hour,
            }
            for g in GPU_TYPES
        ]
    }


def _status_payload(live_pods: int = 0) -> dict:
    return {
        "connected": _SESSION.is_connected(),
        "network_volume_id": _SESSION.network_volume_id,
        "live_pods": live_pods,
        # Where the live key came from, so the UI can explain an already-connected session
        # rather than looking like it stashed a secret behind the user's back.
        "key_source": _SESSION.key_source,
        "connection_error": _SESSION.connection_error,
    }
