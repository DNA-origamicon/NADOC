#!/usr/bin/env python3
"""Shared, confirm-gated pod lifecycle for the GPU-bench campaign.

One implementation of "rent a container-disk pod, PROVE it is up, hand back an SSH
connection, and on the way out PROVE it is destroyed" — so every campaign script (fetch,
bench, future stage) goes through the exact same three confirmation receipts. That is the
whole reusable-safety point: the lifecycle is the deliverable, the benchmark is just its
first caller.

Container-disk only, NO network volume: a volume pins the pod to one datacenter, and the
whole reason this campaign exists is to reach H100/H200 wherever RunPod has them. Everything
travels over SFTP to the pod's own disk and dies with the pod.
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.runpod_api import (  # noqa: E402
    DEFAULT_ALLOWED_CUDA, DEFAULT_IMAGE, RunpodClient, ssh_endpoint,
)
from backend.core.runpod_conn import RunpodConnection  # noqa: E402
from experiments.exp43_runpod_bench.runpod_confirm import (  # noqa: E402
    ConfirmationLog, NoConfirmation, confirm_pod_terminated, confirm_pod_up, guarded_step,
)
from experiments.exp43_runpod_bench.spend_ledger import SpendLedger  # noqa: E402

# Isolated from the production ledgers (see pod_watchdog for why this path, not nadoc_jobs/).
CAMPAIGN_DIR = Path("/media/jojo/Archive/nadoc_bench_campaign")
SSH_KEY = str(Path.home() / ".ssh" / "id_ed25519")


def campaign_ledger() -> SpendLedger:
    return SpendLedger(CAMPAIGN_DIR / "spend.json")


def campaign_log() -> ConfirmationLog:
    return ConfirmationLog(CAMPAIGN_DIR)


def container_payload(name: str, gpu_type_ids: list[str], *, disk_gb: int = 40,
                      env: dict = None) -> dict:
    """A container-disk-only, on-demand, SECURE pod. No networkVolumeId -> not region-pinned.

    ``env`` is injected into the pod's PID-1 environment (readable by the deadman via
    /proc/1/environ) — used to hand it a RUNPOD_KILL_KEY authorised to self-terminate the pod,
    since the pod's auto-injected RUNPOD_API_KEY is NOT (it 403s the DELETE)."""
    payload = {
        "name": name,
        "imageName": DEFAULT_IMAGE,
        "computeType": "GPU",
        "cloudType": "SECURE",
        "gpuTypeIds": list(gpu_type_ids),
        "gpuCount": 1,
        "containerDiskInGb": disk_gb,
        "ports": ["22/tcp"],
        "interruptible": False,          # on-demand: a reclaim mid-benchmark just wastes money
        "allowedCudaVersions": list(DEFAULT_ALLOWED_CUDA),
    }
    if env:
        payload["env"] = dict(env)
    return payload


@contextlib.asynccontextmanager
async def confirmed_pod(client: RunpodClient, ledger: SpendLedger, clog: ConfirmationLog,
                        payload: dict, label: str, *, fallbacks=None, usd_hr_hint: float = 0.0,
                        wait_timeout_s: float = 600.0):
    """Rent a pod, CONFIRM it is up, yield (pod, conn), and CONFIRM it is destroyed.

    - billing is booked into the ledger the instant the pod exists (on_created), not at yield.
    - `client.pod()` guarantees termination in its finally; we additionally re-query and prove
      the pod is gone (guarded_step 'terminate'). An unconfirmed teardown lands in the review
      queue and raises NoConfirmation — the campaign refuses to keep spending on an account it
      cannot prove is clean.
    """
    seen: list[str] = []

    def _booked(info):
        seen.append(info.id)
        ledger.open_pod(info.id, float(info.cost_per_hr or usd_hr_hint), note=f"{label}")

    conn = None
    try:
        async with client.pod(payload, fallbacks=fallbacks, on_created=_booked,
                              wait_timeout_s=wait_timeout_s) as pod:
            async with guarded_step("setup", pod.id, clog) as step:
                step.receipt(await confirm_pod_up(client, pod.id))
            host, port = ssh_endpoint(pod)
            conn = RunpodConnection(host=host, port=port, pod_id=pod.id, client_keys=[SSH_KEY])
            await conn.connect()
            yield pod, conn
    finally:
        if conn is not None:
            with contextlib.suppress(Exception):
                await conn.close()
        # the pod is now terminated by client.pod()'s finally — PROVE it, for each pod booked.
        for pid in seen:
            async with guarded_step("terminate", pid, clog) as step:
                step.receipt(await confirm_pod_terminated(client, pid))
            ledger.close_pod(pid)
