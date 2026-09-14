#!/usr/bin/env python3
"""Recover receipts when Alpine computation finished but post-processing failed."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repair_case_completions(
    *, campaign_manifest_path: Path, results_root: Path, output_path: Path
) -> dict[str, Any]:
    """Validate complete task pairs and materialize only missing case receipts."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite repair report: {output_path}")
    campaign = json.loads(campaign_manifest_path.read_text())
    if (
        campaign.get("schema") != "nadoc.photoproduct-alpine-qm-campaign.v1"
        or campaign.get("case_count") != len(campaign.get("cases") or [])
    ):
        raise ValueError("campaign manifest is malformed")

    repaired = []
    reused = []
    for expected in campaign["cases"]:
        product = expected["product_id"]
        conformer = expected["conformer_id"]
        roots = sorted((results_root / product / conformer).glob("*_*/"))
        valid_roots = []
        failures = []
        for root in roots:
            plan_path = root / "case/distributed/distributed_hessian_plan.json"
            if not plan_path.is_file() or _sha256(plan_path) != expected["plan_sha256"]:
                failures.append(f"{root.name}: missing or mismatched plan")
                continue
            plan = json.loads(plan_path.read_text())
            task_records = []
            for task in plan.get("tasks") or []:
                result = plan_path.parent / task["result"]["path"]
                run = plan_path.parent / task["run_record"]["path"]
                if not result.is_file() or not run.is_file():
                    failures.append(f"{root.name}: incomplete pair {task['id']}")
                    break
                run_payload = json.loads(run.read_text())
                if (
                    run_payload.get("status") != "completed_unreviewed"
                    or run_payload.get("plan_sha256") != expected["plan_sha256"]
                    or run_payload.get("task_id") != task["id"]
                    or (run_payload.get("result") or {}).get("sha256")
                    != _sha256(result)
                ):
                    failures.append(f"{root.name}: invalid receipt {task['id']}")
                    break
                task_records.append(
                    {
                        "task_id": task["id"],
                        "result_sha256": _sha256(result),
                        "run_sha256": _sha256(run),
                    }
                )
            else:
                if len(task_records) != expected["task_count"]:
                    failures.append(f"{root.name}: task count mismatch")
                    continue
                valid_roots.append((root, task_records))
        if len(valid_roots) != 1:
            raise ValueError(
                f"expected one complete result tree for {product} {conformer}, "
                f"found {len(valid_roots)}; diagnostics: {failures}"
            )
        root, task_records = valid_roots[0]
        completion_path = root / "case_completion.json"
        if completion_path.exists():
            existing = json.loads(completion_path.read_text())
            if (
                existing.get("schema")
                != "nadoc.photoproduct-alpine-qm-case.v1"
                or existing.get("plan_sha256") != expected["plan_sha256"]
                or existing.get("task_count") != expected["task_count"]
            ):
                raise ValueError(f"existing completion receipt is invalid: {completion_path}")
            reused.append(str(completion_path.resolve()))
            continue
        match = re.fullmatch(r"(?P<job>\d+)_(?P<array>\d+)", root.name)
        report = {
            "schema": "nadoc.photoproduct-alpine-qm-case.v1",
            "status": "completed_unreviewed",
            "gate_effect": "none",
            "simulation_ready": False,
            "product_id": product,
            "conformer_id": conformer,
            "task_count": expected["task_count"],
            "plan_sha256": expected["plan_sha256"],
            "slurm": {
                "job_id": match.group("job") if match else None,
                "array_task_id": match.group("array") if match else None,
                "postcompute_receipt_recovered": True,
            },
            "recovered_at": datetime.now(timezone.utc).isoformat(),
            "tasks": task_records,
            "interpretation": (
                "All QCSchema task pairs and their original run receipts completed and "
                "passed hash validation. Only the case-level receipt was reconstructed "
                "after the original Alpine runner read its durable copy before syncing it."
            ),
        }
        completion_path.write_text(json.dumps(report, indent=2) + "\n")
        repaired.append(str(completion_path.resolve()))

    result = {
        "schema": "nadoc.photoproduct-alpine-qm-receipt-repair.v1",
        "status": "complete",
        "gate_effect": "none",
        "simulation_ready": False,
        "campaign_manifest": {
            "path": str(campaign_manifest_path.resolve()),
            "sha256": _sha256(campaign_manifest_path),
        },
        "case_count": campaign["case_count"],
        "repaired_count": len(repaired),
        "reused_count": len(reused),
        "repaired_receipts": repaired,
        "reused_receipts": reused,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-manifest", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    print(
        json.dumps(
            repair_case_completions(
                campaign_manifest_path=args.campaign_manifest,
                results_root=args.results_root,
                output_path=args.output,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
