#!/usr/bin/env python3
"""Import and audit Alpine full d(TpT) electrostatic-potential results."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.parameterization.photoproduct_esp import audit_esp_job  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(*, campaign_root: Path, remote_results: Path) -> dict[str, object]:
    report_path = campaign_root / "collection_report.json"
    if report_path.exists():
        raise FileExistsError(f"refusing to overwrite collection report: {report_path}")
    campaign_path = campaign_root / "campaign_manifest.json"
    campaign = json.loads(campaign_path.read_text())
    if campaign.get(
        "schema"
    ) != "nadoc.photoproduct-alpine-boundary-esp-campaign.v1" or campaign.get(
        "product_count"
    ) != len(campaign.get("products") or []):
        raise ValueError("local boundary-ESP campaign manifest is invalid")
    products: list[dict[str, object]] = []
    required = ("output.dat", "grid_esp.dat")
    for record in campaign["products"]:
        product_id = record["product_id"]
        local_case = campaign_root / "bundle/cases" / product_id
        case_path = local_case / "case_manifest.json"
        case = json.loads(case_path.read_text())
        if _sha256(case_path) != record["case_manifest_sha256"]:
            raise ValueError(f"{product_id}: local case manifest changed")
        completions = sorted(
            remote_results.glob(f"{product_id}/*/case_completion.json")
        )
        if len(completions) != 1:
            products.append(
                {
                    "product_id": product_id,
                    "status": "missing_or_ambiguous_completion",
                    "completion_count": len(completions),
                }
            )
            continue
        completion_path = completions[0]
        completion = json.loads(completion_path.read_text())
        remote_case = completion_path.parent / "case"
        remote_job = remote_case / "job"
        valid_receipt = (
            completion.get("schema")
            == "nadoc.photoproduct-alpine-boundary-esp-case-completion.v1"
            and completion.get("product_id") == product_id
            and completion.get("case_manifest_sha256") == record["case_manifest_sha256"]
            and (remote_case / "case_manifest.json").is_file()
            and _sha256(remote_case / "case_manifest.json")
            == record["case_manifest_sha256"]
            and (remote_job / "job_manifest.json").is_file()
            and _sha256(remote_job / "job_manifest.json") == case["job_manifest_sha256"]
            and (remote_job / "input.dat").is_file()
            and _sha256(remote_job / "input.dat") == case["input_sha256"]
            and (remote_job / "grid.dat").is_file()
            and _sha256(remote_job / "grid.dat") == case["grid_sha256"]
        )
        if not valid_receipt:
            products.append(
                {"product_id": product_id, "status": "invalid_completion_receipt"}
            )
            continue
        if completion.get("status") != "completed_unreviewed":
            products.append(
                {
                    "product_id": product_id,
                    "status": "esp_failed_preserved",
                    "returncode": completion.get("returncode"),
                    "completion": {
                        "path": str(completion_path),
                        "sha256": _sha256(completion_path),
                    },
                }
            )
            continue
        outputs = completion.get("outputs") or {}
        if any(
            not (remote_job / name).is_file()
            or _sha256(remote_job / name) != (outputs.get(name) or {}).get("sha256")
            for name in required
        ):
            products.append(
                {"product_id": product_id, "status": "output_hash_mismatch"}
            )
            continue
        local_job = local_case / "job"
        if any(
            (local_job / name).exists()
            for name in (*required, "run_manifest.json", "esp_audit.json")
        ):
            raise FileExistsError(f"refusing to overwrite imported result: {local_job}")
        for name in required:
            shutil.copyfile(remote_job / name, local_job / name)
        run = {
            "schema": "nadoc.photoproduct-qm-run.v1",
            "status": "completed_unreviewed",
            "gate_effect": "none",
            "job_manifest_sha256": case["job_manifest_sha256"],
            "command": [
                "/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/envs/nadoc-qm-1.11/bin/psi4",
                "input.dat",
                "output.dat",
            ],
            "scratch_dir": "Alpine SLURM_SCRATCH (ephemeral)",
            "returncode": completion.get("returncode"),
            "stdout_tail": "",
            "stderr_tail": "",
            "outputs": {
                name: {
                    "path": str((local_job / name).resolve()),
                    "sha256": _sha256(local_job / name),
                    "bytes": (local_job / name).stat().st_size,
                }
                for name in required
            },
            "remote_completion": {
                "path": str(completion_path.resolve()),
                "sha256": _sha256(completion_path),
                "slurm": completion.get("slurm"),
            },
        }
        (local_job / "run_manifest.json").write_text(json.dumps(run, indent=2) + "\n")
        audit = audit_esp_job(local_job)
        products.append(
            {
                "product_id": product_id,
                "status": audit["status"],
                "point_count": audit["point_count"],
                "minimum_potential": audit["minimum_potential"],
                "maximum_potential": audit["maximum_potential"],
                "dipole": audit["dipole"],
                "esp_audit": {
                    "path": str((local_job / "esp_audit.json").resolve()),
                    "sha256": _sha256(local_job / "esp_audit.json"),
                },
            }
        )
    passed = sum(item["status"] == "complete_candidate" for item in products)
    report = {
        "schema": "nadoc.photoproduct-alpine-boundary-esp-collection.v1",
        "status": "passed_esp_import_and_audits"
        if passed == len(products)
        else "incomplete_or_failed",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_count": len(products),
        "passed_product_count": passed,
        "products": products,
        "source_campaign": {
            "path": str(campaign_path.resolve()),
            "sha256": _sha256(campaign_path),
        },
        "interpretation": (
            "Full-boundary electrostatic-potential evidence only; charge fitting and "
            "independent MM validation remain required."
        ),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--remote-results", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            collect(
                campaign_root=args.campaign_root.resolve(),
                remote_results=args.remote_results.resolve(),
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
