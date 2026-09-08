#!/usr/bin/env python3
"""Run independent TT-CPD nonbonded audits after an Alpine water campaign.

The runner is deliberately gate-neutral.  It verifies that candidate product identities
form an exact partition of the validation campaign, refuses to treat training evidence as
validation, and records failed scientific targets as results rather than hiding them.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.parameterization.photoproduct_nonbonded_transfer import (  # noqa: E402
    audit_joint_nonbonded_candidate,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _under_storage(path: Path, storage_root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(storage_root.resolve())
    except ValueError as exc:
        raise ValueError(f"path is outside Archive storage: {resolved}") from exc
    return resolved


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(path)


def _candidate_inventory(
    candidate_paths: list[Path], validation_products: set[str]
) -> list[dict[str, Any]]:
    inventory = []
    claimed: dict[str, Path] = {}
    for path in candidate_paths:
        candidate = json.loads(path.read_text())
        if (
            candidate.get("schema")
            != "nadoc.photoproduct-joint-nonbonded-fit.v1"
            or candidate.get("simulation_ready") is not False
            or candidate.get("gate_effect") != "none"
        ):
            raise ValueError(f"candidate is not a gate-neutral joint fit: {path}")
        product_ids = [str(item) for item in candidate.get("product_ids") or []]
        if not product_ids or len(product_ids) != len(set(product_ids)):
            raise ValueError(f"candidate product inventory is empty or duplicated: {path}")
        for product_id in product_ids:
            if product_id in claimed:
                raise ValueError(
                    f"product {product_id} is claimed by both {claimed[product_id]} and {path}"
                )
            claimed[product_id] = path
        inventory.append(
            {
                "path": path,
                "source": _source(path),
                "product_ids": sorted(product_ids),
            }
        )
    if set(claimed) != validation_products:
        missing = sorted(validation_products - set(claimed))
        unexpected = sorted(set(claimed) - validation_products)
        raise ValueError(
            "candidate partition differs from validation products; "
            f"missing={missing}, unexpected={unexpected}"
        )
    return inventory


def _reusable_report(
    path: Path,
    *,
    candidate: dict[str, str],
    validation: dict[str, str],
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    report = json.loads(path.read_text())
    sources = report.get("sources") or {}
    if (
        report.get("schema")
        != "nadoc.photoproduct-independent-nonbonded-validation.v1"
        or report.get("simulation_ready") is not False
        or report.get("gate_effect") != "none"
        or sources.get("candidate") != candidate
        or sources.get("validation_collection") != validation
    ):
        raise ValueError(f"existing independent validation is stale: {path}")
    return report


def run(args: argparse.Namespace) -> dict[str, Any]:
    storage_root = args.storage_root.resolve()
    validation_path = _under_storage(args.validation_collection, storage_root)
    output_root = _under_storage(args.output_root, storage_root)
    candidate_paths = [
        _under_storage(path, storage_root) for path in args.candidate
    ]
    for required in (
        validation_path,
        args.cgenff_parameters.resolve(),
        args.nucleic_parameters.resolve(),
        *candidate_paths,
    ):
        if not required.is_file():
            raise FileNotFoundError(required)

    collection = json.loads(validation_path.read_text())
    if (
        collection.get("schema")
        != "nadoc.photoproduct-alpine-water-collection.v1"
        or collection.get("status") != "passed_import_and_curve_audits"
        or collection.get("gate_effect") != "none"
    ):
        raise ValueError("validation water collection is not a passed gate-neutral receipt")
    validation_products = {
        str(item.get("product_id")) for item in collection.get("products") or []
    }
    if len(validation_products) != int(collection.get("product_count", -1)):
        raise ValueError("validation collection has duplicate or incomplete product identity")
    candidates = _candidate_inventory(candidate_paths, validation_products)
    validation_source = _source(validation_path)

    records = []
    for candidate in candidates:
        output_path = output_root / (
            f"{candidate['path'].stem}-independent-validation-v1.json"
        )
        report = _reusable_report(
            output_path,
            candidate=candidate["source"],
            validation=validation_source,
        )
        if report is None:
            report = audit_joint_nonbonded_candidate(
                candidate_path=candidate["path"],
                validation_collection_path=validation_path,
                cgenff_parameters_path=args.cgenff_parameters.resolve(),
                nucleic_parameters_path=args.nucleic_parameters.resolve(),
                output_path=output_path,
            )
        records.append(
            {
                "candidate": candidate["source"],
                "product_ids": candidate["product_ids"],
                "audit": _source(output_path),
                "passed": bool(report["passed"]),
            }
        )

    passed_count = sum(record["passed"] for record in records)
    summary = {
        "schema": "nadoc.photoproduct-post-water-validation.v1",
        "status": (
            "passed_all_independent_nonbonded_targets"
            if passed_count == len(records)
            else "completed_with_candidate_rejections"
        ),
        "created_at": _now(),
        "simulation_ready": False,
        "gate_effect": "none",
        "validation_collection": validation_source,
        "candidate_count": len(records),
        "product_count": len(validation_products),
        "passed_candidate_count": passed_count,
        "failed_candidate_count": len(records) - passed_count,
        "candidates": records,
        "interpretation": (
            "Independent alternate-orientation water tests of fixed-LJ charge models. "
            "Passing does not release parameters; failures remain evidence for the next "
            "model-form comparison."
        ),
    }
    summary_path = output_root / "post_water_validation_summary.json"
    if summary_path.exists():
        existing = json.loads(summary_path.read_text())
        comparable = {key: value for key, value in summary.items() if key != "created_at"}
        old_comparable = {
            key: value for key, value in existing.items() if key != "created_at"
        }
        if comparable != old_comparable:
            raise ValueError(f"existing post-water summary is stale: {summary_path}")
        return existing
    _write_json_atomic(summary_path, summary)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--validation-collection", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, action="append", required=True)
    parser.add_argument("--cgenff-parameters", type=Path, required=True)
    parser.add_argument("--nucleic-parameters", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> int:
    report = run(_parser().parse_args())
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
