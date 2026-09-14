#!/usr/bin/env python3
"""Import hash-verified Alpine task pairs into their Archive-backed local plans."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.parameterization.photoproduct_distributed_hessian import (  # noqa: E402
    checkpoint_distributed_hessian_pairs,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_campaign_results(
    *,
    campaign_manifest_path: Path,
    remote_results_root: Path,
    work_root: Path,
    output_path: Path,
) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite campaign import: {output_path}")
    campaign = json.loads(campaign_manifest_path.read_text())
    if (
        campaign.get("schema") != "nadoc.photoproduct-alpine-qm-campaign.v1"
        or campaign.get("status") != "prepared_not_submitted"
        or campaign.get("gate_effect") != "none"
        or campaign.get("case_count") != len(campaign.get("cases") or [])
    ):
        raise ValueError("campaign manifest is malformed")

    selected: list[dict[str, Any]] = []
    for case in campaign["cases"]:
        product = str(case["product_id"])
        conformer = str(case["conformer_id"])
        candidates = []
        case_root = remote_results_root / product / conformer
        for report_path in sorted(case_root.glob("*/case_completion.json")):
            report = json.loads(report_path.read_text())
            if (
                report.get("schema") == "nadoc.photoproduct-alpine-qm-case.v1"
                and report.get("status") == "completed_unreviewed"
                and report.get("gate_effect") == "none"
                and report.get("product_id") == product
                and report.get("conformer_id") == conformer
                and report.get("task_count") == case["task_count"]
                and report.get("plan_sha256") == case["plan_sha256"]
            ):
                candidates.append((report_path, report))
        if len(candidates) != 1:
            raise ValueError(
                f"expected one matching Alpine completion for {product} {conformer}, "
                f"found {len(candidates)}"
            )
        report_path, report = candidates[0]
        source_plan = report_path.parent / "case/distributed/distributed_hessian_plan.json"
        destination_plan = (
            work_root / product / conformer / "distributed/distributed_hessian_plan.json"
        )
        if (
            not source_plan.is_file()
            or not destination_plan.is_file()
            or _sha256(source_plan) != case["plan_sha256"]
            or source_plan.read_bytes() != destination_plan.read_bytes()
        ):
            raise ValueError(f"Alpine/local plan mismatch for {product} {conformer}")

        source_plan_payload = json.loads(source_plan.read_text())
        by_id = {item["task_id"]: item for item in report.get("tasks") or []}
        if len(by_id) != case["task_count"]:
            raise ValueError(
                f"Alpine completion task count is invalid for {product} {conformer}"
            )
        for task in source_plan_payload["tasks"]:
            record = by_id.get(task["id"])
            result = source_plan.parent / task["result"]["path"]
            run = source_plan.parent / task["run_record"]["path"]
            if (
                record is None
                or not result.is_file()
                or not run.is_file()
                or record.get("result_sha256") != _sha256(result)
                or record.get("run_sha256") != _sha256(run)
            ):
                raise ValueError(
                    f"Alpine task evidence changed: {product} {conformer} {task['id']}"
                )
        selected.append(
            {
                "case": case,
                "report_path": report_path,
                "source_plan": source_plan,
                "destination_plan": destination_plan,
            }
        )

    imported = []
    for item in selected:
        case = item["case"]
        checkpoint_path = (
            item["destination_plan"].parents[1] / "alpine-checkpoint-v2.1.0.json"
        )
        checkpoint = checkpoint_distributed_hessian_pairs(
            source_plan_path=item["source_plan"],
            destination_plan_path=item["destination_plan"],
            output_path=checkpoint_path,
        )
        if (
            checkpoint["copied_pair_count"] + checkpoint["reused_pair_count"]
            != case["task_count"]
            or checkpoint["pending_pair_count"] != 0
        ):
            raise RuntimeError(
                f"incomplete local checkpoint for {case['product_id']} "
                f"{case['conformer_id']}"
            )
        imported.append(
            {
                "product_id": case["product_id"],
                "conformer_id": case["conformer_id"],
                "task_count": case["task_count"],
                "remote_completion": {
                    "path": str(item["report_path"].resolve()),
                    "sha256": _sha256(item["report_path"]),
                },
                "checkpoint": {
                    "path": str(checkpoint_path.resolve()),
                    "sha256": _sha256(checkpoint_path),
                },
            }
        )

    result = {
        "schema": "nadoc.photoproduct-alpine-qm-import.v1",
        "status": "complete_task_pairs_imported",
        "gate_effect": "none",
        "simulation_ready": False,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "campaign_manifest": {
            "path": str(campaign_manifest_path.resolve()),
            "sha256": _sha256(campaign_manifest_path),
        },
        "case_count": len(imported),
        "task_count": sum(item["task_count"] for item in imported),
        "cases": imported,
        "interpretation": (
            "All remote task pairs were checked against the remote completion receipt "
            "and copied into byte-identical local plans. Normal local Hessian assembly "
            "and response audits are still required."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-manifest", type=Path, required=True)
    parser.add_argument("--remote-results-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    print(
        json.dumps(
            import_campaign_results(
                campaign_manifest_path=args.campaign_manifest,
                remote_results_root=args.remote_results_root,
                work_root=args.work_root,
                output_path=args.output,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
