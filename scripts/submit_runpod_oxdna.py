#!/usr/bin/env python3
"""Submit one prepared NADOC oxDNA job to RunPod.

This is the supported headless interface for the first RunPod phase.  It updates the
existing ``OxdnaJob`` record, fetches outputs into its normal stage directories, and
destroys the metered pod on every exit path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.oxdna_job import OxdnaJob, OxdnaStatus
from backend.core.oxdna_runner import load_stage_specs
from backend.core.runpod_api import RunpodClient, resolve_api_key
from backend.core.runpod_oxdna import (
    CampaignLedger,
    GPU_TARGETS,
    run_prepared_job_on_pod,
)
from backend.core.runpod_preflight import fetch_gpu_stock


def _target(name: str):
    return GPU_TARGETS[0] if name == "h200" else GPU_TARGETS[1]


async def submit(args) -> dict:
    workspace = args.workspace.resolve()
    job = OxdnaJob.load(args.job_id, workspace)
    job_dir = job.job_dir(workspace)
    specs = load_stage_specs(job_dir)
    if not specs:
        raise RuntimeError(f"job {job.job_id} has no stages_spec.json")
    resolved = resolve_api_key()
    if not resolved.value:
        raise RuntimeError("RunPod API key unavailable ($RUNPOD_API_KEY or ~/.runpod_key)")
    target = _target(args.gpu)
    client = RunpodClient(resolved.value, audit_dir=job_dir)
    ledger = CampaignLedger(args.ledger.resolve(), cap_usd=args.budget)
    try:
        stock = await fetch_gpu_stock(resolved.value)
        quote = stock.get(target.gpu_id) or {}
        rate = float(quote.get("on_demand") or 0.0)
        if rate <= 0:
            raise RuntimeError(f"no live on-demand quote for {target.label}")
        volume_id = args.volume
        if volume_id is None and not args.no_volume:
            volumes = await client.list_network_volumes()
            if len(volumes) != 1:
                raise RuntimeError("pass --volume: account does not have exactly one volume")
            volume_id = volumes[0]["id"]
        if args.no_volume:
            volume_id = ""

        job.execution_target = "runpod"
        job.runpod_gpu_key = target.gpu_id
        job.runpod_budget_usd = args.budget
        job.status = OxdnaStatus.running
        job.error = None
        job.save(workspace)

        def created(pod_id: str, _rate: float) -> None:
            job.runpod_pod_id = pod_id
            job.save(workspace)

        def update(message: str) -> None:
            print(message, flush=True)

        result = await run_prepared_job_on_pod(
            client=client,
            network_volume_id=volume_id or "",
            target=target,
            quoted_rate_usd_per_hour=rate,
            ledger=ledger,
            job_id=job.job_id,
            job_dir=job_dir,
            specs=specs,
            patch_path=ROOT / "tools/oxdna_memory/adaptive-neighbor-lists.patch",
            result_dir=job_dir,
            lifetime_s=args.max_seconds,
            on_pod_created=created,
            on_update=update,
        )
        for stage in job.stages:
            stage.status = "done"
        job.current_stage_idx = len(job.stages)
        job.status = OxdnaStatus.completed
        job.runpod_pod_id = None
        job.runpod_final_cost_usd = ledger.spent_usd()
        job.save(workspace)
        result["campaign_spent_usd"] = job.runpod_final_cost_usd
        return result
    except Exception as exc:
        job.runpod_pod_id = None
        job.status = OxdnaStatus.failed
        job.error = str(exc)
        job.runpod_final_cost_usd = ledger.spent_usd()
        job.save(workspace)
        raise
    finally:
        await client.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", help="prepared workspace/oxdna_jobs job id")
    parser.add_argument("--workspace", type=Path, default=ROOT / "workspace")
    parser.add_argument("--gpu", choices=("h200", "rtx6000"), default="rtx6000")
    parser.add_argument("--volume", help="RunPod network-volume id")
    parser.add_argument("--no-volume", action="store_true", help="allow any datacenter")
    parser.add_argument("--budget", type=float, default=5.0)
    parser.add_argument("--max-seconds", type=int, default=6000)
    parser.add_argument(
        "--ledger", type=Path,
        default=ROOT / "workspace/runpod_oxdna_campaign_spend.json",
    )
    args = parser.parse_args()
    if args.budget <= 0 or args.budget > 5.0:
        parser.error("--budget must be greater than zero and at most $5")
    try:
        result = asyncio.run(submit(args))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
