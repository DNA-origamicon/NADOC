#!/usr/bin/env python3
"""Import and audit the prioritized Alpine boundary-recovery results."""

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

from backend.parameterization.photoproduct_qm import (  # noqa: E402
    audit_optimized_model,
    parse_psi4_output,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(*, campaign_root: Path, remote_results: Path) -> dict[str, object]:
    report_path = campaign_root / "collection_report.json"
    if report_path.exists():
        raise FileExistsError(f"refusing to overwrite collection report: {report_path}")
    campaign_path = campaign_root / "campaign_manifest.json"
    campaign = json.loads(campaign_path.read_text())
    records = campaign.get("products") or []
    if (
        campaign.get("schema")
        != "nadoc.photoproduct-alpine-boundary-recovery-campaign.v1"
        or campaign.get("compute_product_count") != len(records)
        or len(records) != 3
    ):
        raise ValueError("local boundary-recovery campaign manifest is invalid")
    products: list[dict[str, object]] = []
    for record in records:
        product_id = record["product_id"]
        local_case = campaign_root / "bundle/cases" / product_id
        case_path = local_case / "case_manifest.json"
        case = json.loads(case_path.read_text())
        if _sha256(case_path) != record["case_manifest_sha256"]:
            raise ValueError(f"{product_id}: local case manifest changed")
        completions = sorted(remote_results.glob(f"{product_id}/*/case_completion.json"))
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
            == "nadoc.photoproduct-alpine-boundary-recovery-case-completion.v1"
            and completion.get("product_id") == product_id
            and completion.get("case_manifest_sha256")
            == record["case_manifest_sha256"]
            and (remote_case / "case_manifest.json").is_file()
            and _sha256(remote_case / "case_manifest.json")
            == record["case_manifest_sha256"]
            and (remote_job / "job_manifest.json").is_file()
            and _sha256(remote_job / "job_manifest.json")
            == case["job_manifest_sha256"]
            and (remote_job / "input.dat").is_file()
            and _sha256(remote_job / "input.dat") == case["input_sha256"]
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
                    "status": "optimization_failed_preserved",
                    "returncode": completion.get("returncode"),
                    "completion": {
                        "path": str(completion_path.resolve()),
                        "sha256": _sha256(completion_path),
                    },
                    "checkpoint_available": (remote_job / "checkpoint_latest.xyz").is_file(),
                }
            )
            continue
        output_records = completion.get("outputs") or {}
        required = ("output.dat", "optimized.xyz")
        if any(
            not (remote_job / name).is_file()
            or _sha256(remote_job / name)
            != (output_records.get(name) or {}).get("sha256")
            for name in required
        ):
            products.append({"product_id": product_id, "status": "output_hash_mismatch"})
            continue
        local_job = local_case / "job"
        if any(
            (local_job / name).exists()
            for name in (*required, "run_manifest.json", "optimized_model_audit.json")
        ):
            raise FileExistsError(f"refusing to overwrite imported result: {local_job}")
        for name in required:
            shutil.copyfile(remote_job / name, local_job / name)
        parsed = parse_psi4_output(
            (local_job / "output.dat").read_text(errors="replace"),
            "geometry_optimization",
        )
        run = {
            "schema": "nadoc.photoproduct-qm-run.v1",
            "status": (
                "completed_unreviewed" if parsed["passed_execution_checks"] else "failed"
            ),
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
            "parsed": parsed,
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
        if not parsed["passed_execution_checks"]:
            products.append({"product_id": product_id, "status": "output_parse_failed"})
            continue
        audit = audit_optimized_model(local_job)
        status = (
            "passed_identity_and_chirality"
            if audit.get("status") == "passed_identity_and_chirality"
            else "optimized_geometry_audit_failed"
        )
        products.append(
            {
                "product_id": product_id,
                "status": status,
                "final_energy_hartree": audit.get("final_energy_hartree"),
                "optimized_model_audit": {
                    "path": str((local_job / "optimized_model_audit.json").resolve()),
                    "sha256": _sha256(local_job / "optimized_model_audit.json"),
                },
            }
        )
    passed = sum(item["status"] == "passed_identity_and_chirality" for item in products)
    recovered_path = Path(str((campaign.get("recovered_evidence") or {}).get("path") or ""))
    recovered_valid = (
        recovered_path.is_file()
        and _sha256(recovered_path) == campaign["recovered_evidence"]["sha256"]
        and json.loads(recovered_path.read_text()).get("status")
        == "recovered_completed_unreviewed"
    )
    report = {
        "schema": "nadoc.photoproduct-alpine-boundary-recovery-collection.v1",
        "status": (
            "passed_first_wave_optimization_identity_audits"
            if passed == len(products) and recovered_valid
            else "incomplete_or_failed"
        ),
        "gate_effect": "none",
        "simulation_ready": False,
        "compute_product_count": len(products),
        "passed_compute_product_count": passed,
        "recovered_trans_syn_i_valid": recovered_valid,
        "products": products,
        "source_campaign": {
            "path": str(campaign_path.resolve()),
            "sha256": _sha256(campaign_path),
        },
        "next_required_step": "Run minimum/family-transfer diagnostics for the first wave. Do not launch all-eight Hessians unless a registered held-out transfer test requires a split.",
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
