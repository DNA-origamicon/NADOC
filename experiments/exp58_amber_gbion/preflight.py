#!/usr/bin/env python3
"""Fail-closed local preflight for the paid native Amber26 GBION gate."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.runpod_api import RunpodClient  # noqa: E402
from experiments.exp43_runpod_bench.runpod_confirm import ConfirmationLog  # noqa: E402
from experiments.exp43_runpod_bench.spend_ledger import SpendLedger  # noqa: E402
from experiments.exp58_amber_gbion.model import (  # noqa: E402
    EXPECTED_AMBER26_MD5,
    EXPECTED_AMBER26_SHA256,
    require_amber26_archive,
)

DEFAULT_ARCHIVE = Path("/media/jojo/Archive/nadoc_amber_exp58/duplex_runpod")
BUDGET_USD = 5.0
TEARDOWN_RESERVE_USD = 0.25


def digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def inspect_account(key: str, audit_dir: Path) -> dict:
    client = RunpodClient(key, audit_dir=audit_dir)
    try:
        pods = await client.list_pods()
        volumes = await client.list_network_volumes()
        return {
            "pods": [
                {
                    "id": pod.id,
                    "name": pod.raw.get("name"),
                    "status": pod.desired_status,
                    "usd_per_hour": pod.cost_per_hr,
                }
                for pod in pods
            ],
            "volumes": volumes,
        }
    finally:
        await client.aclose()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--amber26",
        type=Path,
        default=os.environ.get("NADOC_AMBER26_TARBALL", "pmemd26.tar.bz2"),
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    args = parser.parse_args()

    # The licensed payload is checked before credentials and before any provider call.
    amber = require_amber26_archive(args.amber26)
    args.archive.mkdir(parents=True, exist_ok=True)
    confirmations = ConfirmationLog(args.archive)
    confirmations.require_clean()
    ledger = SpendLedger(args.archive / "spend.json")
    spent = ledger.spent()
    if spent >= BUDGET_USD - TEARDOWN_RESERVE_USD:
        raise RuntimeError(f"exp58 budget unavailable: ${spent:.4f} already spent")

    key_path = Path.home() / ".runpod_key"
    key = os.environ.get("RUNPOD_API_KEY") or (
        key_path.read_text().strip() if key_path.is_file() else ""
    )
    if not key:
        raise RuntimeError("RunPod API key unavailable; no pod was created")
    archive_md5 = digest(amber, "md5")
    archive_sha256 = digest(amber, "sha256")
    if archive_md5 != EXPECTED_AMBER26_MD5:
        raise RuntimeError(
            f"Amber26 MD5 mismatch: {archive_md5}; expected {EXPECTED_AMBER26_MD5}. "
            "No pod was created."
        )
    if archive_sha256 != EXPECTED_AMBER26_SHA256:
        raise RuntimeError(
            f"Amber26 SHA-256 mismatch: {archive_sha256}; expected "
            f"{EXPECTED_AMBER26_SHA256}. No pod was created."
        )

    account = await inspect_account(key, args.archive)
    live = [pod for pod in account["pods"] if pod["status"] != "TERMINATED"]
    owned = [
        pod
        for pod in live
        if pod.get("name") == "nadoc-exp58-amber26-gbion"
        or pod["id"] in set(ledger.live_pods())
    ]
    if owned:
        raise RuntimeError(f"an exp58-owned RunPod pod is already live: {owned}")

    result = {
        "ready": True,
        "budget_usd": BUDGET_USD,
        "teardown_reserve_usd": TEARDOWN_RESERVE_USD,
        "spent_usd": spent,
        "amber26_archive": str(amber),
        "amber26_bytes": amber.stat().st_size,
        "amber26_md5": archive_md5,
        "amber26_sha256": archive_sha256,
        "account": account,
        "unrelated_live_pods_preserved": [pod for pod in live if pod not in owned],
    }
    (args.archive / "preflight.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
