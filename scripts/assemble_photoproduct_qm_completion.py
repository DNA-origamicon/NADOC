#!/usr/bin/env python3
"""Assemble one hash-pinned completion receipt for all TT-CPD response batches."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_post_qm_efficient_sequence import CONFORMERS, PRODUCTS


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assemble_completion(
    *, source_roots: list[Path], output_path: Path
) -> dict[str, Any]:
    """Select exactly one passed, identity-matched batch for every product/conformer."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite QM completion receipt: {output_path}")
    roots = [path.resolve() for path in source_roots]
    if not roots or len(roots) != len(set(roots)) or any(not path.is_dir() for path in roots):
        raise ValueError("unique existing response source roots are required")

    selected = []
    for product in PRODUCTS:
        for suffix in CONFORMERS:
            conformer_id = f"conformer-{suffix}"
            matches = []
            for root in roots:
                case = root / product / conformer_id
                for path in sorted(case.glob("local-batch-report*.json")):
                    payload = json.loads(path.read_text())
                    if (
                        payload.get("schema")
                        == "nadoc.photoproduct-local-fixed-hessian-batch.v1"
                        and payload.get("status") == "passed"
                        and payload.get("simulation_ready") is False
                        and payload.get("gate_effect") == "none"
                        and payload.get("product_id") == product
                        and payload.get("conformer_id") == conformer_id
                        and payload.get("task_count") == 211
                    ):
                        matches.append(path.resolve())
            if len(matches) != 1:
                raise ValueError(
                    f"expected one passed response batch for {product} {conformer_id}, "
                    f"found {len(matches)}"
                )
            path = matches[0]
            selected.append(
                {
                    "product_id": product,
                    "conformer_id": conformer_id,
                    "task_count": 211,
                    "batch_report": {"path": str(path), "sha256": _sha256(path)},
                }
            )

    report = {
        "schema": "nadoc.photoproduct-all-form-response-completion.v1",
        "status": "passed",
        "simulation_ready": False,
        "gate_effect": "none",
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "product_count": len(PRODUCTS),
        "conformer_count": len(selected),
        "task_count": sum(record["task_count"] for record in selected),
        "source_roots": [str(path) for path in roots],
        "batches": selected,
        "interpretation": (
            "Every ordered TT-CPD product has four hash-pinned, passed fixed-geometry "
            "force/Hessian batches. This completes response evidence only and does not "
            "release parameters or authorize simulation."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            assemble_completion(
                source_roots=args.source_root, output_path=args.output
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
