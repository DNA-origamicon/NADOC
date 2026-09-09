#!/usr/bin/env python3
"""Guard one exact RunPod pod from controller loss or a missed provider deadline."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.runpod_api import RunpodClient, resolve_api_key  # noqa: E402
from backend.core.runpod_oxdna import CampaignLedger  # noqa: E402
from backend.core.runpod_watchdog import (  # noqa: E402
    decide_watchdog_action,
    parse_utc_deadline,
    process_identity_alive,
    watchdog_unit_name,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def run_watchdog(
    args: argparse.Namespace,
    *,
    client: RunpodClient,
    sleep=asyncio.sleep,
    now=_utc_now,
) -> dict:
    """Poll until the exact pod is absent, retrying API failures indefinitely."""

    deadline = parse_utc_deadline(args.deadline)
    watchdog_unit_name(args.pod_id)
    ledger = (
        CampaignLedger(args.campaign_ledger, cap_usd=args.campaign_cap_usd)
        if args.campaign_ledger is not None
        else None
    )
    client.record_lifecycle(
        "independent_watchdog_started",
        pod_id=args.pod_id,
        owner_pid=args.owner_pid,
        owner_start_ticks=args.owner_start_ticks,
        deadline=deadline.isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
    trigger: str | None = None
    poll_failures = 0
    while True:
        try:
            pods = await client.list_pods()
        except Exception as exc:  # the systemd service retries; never abandon the meter
            poll_failures += 1
            client.record_lifecycle(
                "independent_watchdog_poll_failed",
                pod_id=args.pod_id,
                failure_count=poll_failures,
                error=f"{type(exc).__name__}: {exc}",
            )
            await sleep(args.poll_seconds)
            continue

        pod_present = any(pod.id == args.pod_id for pod in pods)
        owner_alive = process_identity_alive(
            args.owner_pid, args.owner_start_ticks
        )
        decision = decide_watchdog_action(
            pod_present=pod_present,
            owner_alive=owner_alive,
            now=now(),
            deadline=deadline,
        )
        if decision.action == "complete_provider_absent":
            if ledger is not None:
                ledger.close_pod(args.pod_id)
            client.record_lifecycle(
                "independent_watchdog_confirmed_provider_absent",
                pod_id=args.pod_id,
                trigger=trigger,
                poll_failures=poll_failures,
            )
            return {
                "schema": "nadoc.runpod-exact-pod-watchdog.v1",
                "status": "provider_absent",
                "pod_id": args.pod_id,
                "trigger": trigger,
                "poll_failures": poll_failures,
            }
        if decision.action == "wait":
            await sleep(args.poll_seconds)
            continue

        if trigger is None:
            trigger = decision.action
            client.record_lifecycle(
                "independent_watchdog_triggered",
                pod_id=args.pod_id,
                trigger=trigger,
                reason=decision.reason,
            )
        try:
            await client.terminate_pod(
                args.pod_id,
                reason=f"independent_watchdog:{trigger}",
            )
        except Exception as exc:
            client.record_lifecycle(
                "independent_watchdog_terminate_retry",
                pod_id=args.pod_id,
                trigger=trigger,
                error=f"{type(exc).__name__}: {exc}",
            )
        await sleep(args.poll_seconds)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pod-id", required=True)
    parser.add_argument("--owner-pid", type=int, required=True)
    parser.add_argument("--owner-start-ticks", type=int, required=True)
    parser.add_argument("--deadline", required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--campaign-ledger", type=Path)
    parser.add_argument("--campaign-cap-usd", type=float, default=10.0)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    return parser


async def _main(args: argparse.Namespace) -> dict:
    """Construct and close the HTTP client in the same event loop."""

    resolved = resolve_api_key()
    if not resolved.value:
        raise RuntimeError(
            "RunPod API key is unavailable ($RUNPOD_API_KEY or ~/.runpod_key)"
        )
    client = RunpodClient(resolved.value, audit_dir=args.audit_dir)
    try:
        return await run_watchdog(args, client=client)
    finally:
        await client.aclose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.owner_pid < 1 or args.owner_start_ticks < 1 or args.poll_seconds <= 0:
        raise ValueError("owner identity and poll interval must be positive")
    report = asyncio.run(_main(args))
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
