#!/usr/bin/env python3
"""Run remaining TT-CPD fixed-geometry campaigns in bounded product batches."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any


CONFORMERS = ("001", "002", "003", "004")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _passed(path: Path, product: str, conformer: str) -> bool:
    if not path.is_file():
        return False
    payload = json.loads(path.read_text())
    return (
        payload.get("schema") == "nadoc.photoproduct-local-fixed-hessian-batch.v1"
        and payload.get("status") == "passed"
        and payload.get("product_id") == product
        and payload.get("conformer_id") == f"conformer-{conformer}"
    )


def _report_path(root: Path, product: str, conformer: str) -> Path:
    return root / product / f"conformer-{conformer}" / "local-batch-report-v1.json"


def _run_one(args: argparse.Namespace, product: str, conformer: str) -> dict[str, Any]:
    directory = args.work_root / product / f"conformer-{conformer}"
    report = _report_path(args.work_root, product, conformer)
    if _passed(report, product, conformer):
        return {"conformer": conformer, "reused": True, "report": str(report)}
    if report.exists():
        raise RuntimeError(f"existing response report is not passed: {report}")
    command = [
        str(args.qm_python),
        str(args.runner),
        "--plan",
        str(directory / "distributed/distributed_hessian_plan.json"),
        "--job-dir",
        str(directory / "job"),
        "--scratch-root",
        str(args.scratch_root / f"{product}-{conformer}"),
        "--output",
        str(report),
        "--qm-python",
        str(args.qm_python),
        "--max-parallel",
        "1",
        "--threads",
        "2",
        "--memory-gib",
        "3",
        "--storage-root",
        str(args.storage_root),
    ]
    log_path = directory / "local-queue-run.log"
    with log_path.open("a") as log:
        result = subprocess.run(
            command,
            cwd=args.repository,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if result.returncode or not _passed(report, product, conformer):
        raise RuntimeError(
            f"{product} conformer-{conformer} failed; see {log_path}"
        )
    return {"conformer": conformer, "reused": False, "report": str(report)}


def _wait_for_product(args: argparse.Namespace, product: str) -> None:
    while not all(
        _passed(_report_path(args.work_root, product, conformer), product, conformer)
        for conformer in CONFORMERS
    ):
        time.sleep(args.poll_seconds)


def run_queue(args: argparse.Namespace) -> dict[str, Any]:
    resolved = {
        "storage_root": args.storage_root.resolve(),
        "work_root": args.work_root.resolve(),
        "scratch_root": args.scratch_root.resolve(),
        "output": args.output.resolve(),
    }
    for label, path in resolved.items():
        try:
            path.relative_to(resolved["storage_root"])
        except ValueError as exc:
            raise ValueError(f"{label} must be on the Archive storage root") from exc
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite queue report: {args.output}")
    if args.wait_product:
        _wait_for_product(args, args.wait_product)
    products = []
    for product in args.products:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(_run_one, args, product, conformer): conformer
                for conformer in CONFORMERS
            }
            records = [future.result() for future in as_completed(futures)]
        products.append(
            {
                "product_id": product,
                "responses": [
                    {
                        **record,
                        "sha256": _sha256(Path(record["report"])),
                    }
                    for record in sorted(records, key=lambda item: item["conformer"])
                ],
            }
        )
    report = {
        "schema": "nadoc.photoproduct-local-response-queue.v1",
        "status": "passed",
        "simulation_ready": False,
        "gate_effect": "none",
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "wait_product": args.wait_product,
        "products": products,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--qm-python", type=Path, required=True)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--wait-product")
    parser.add_argument("--product", dest="products", action="append", required=True)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not 10 <= args.poll_seconds <= 600:
        raise ValueError("poll interval must be between 10 and 600 seconds")
    print(json.dumps(run_queue(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
