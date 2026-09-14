#!/usr/bin/env python3
"""Import, hash-audit, and analyze completed Alpine TT-CPD water jobs."""

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
    audit_water_interaction_series,
    parse_psi4_output,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(*, campaign_root: Path, remote_results: Path) -> dict[str, object]:
    report_path = campaign_root / "collection_report.json"
    if report_path.exists():
        raise FileExistsError(f"refusing to overwrite collection report: {report_path}")
    campaign = json.loads((campaign_root / "campaign_manifest.json").read_text())
    if (
        campaign.get("schema") != "nadoc.photoproduct-alpine-water-campaign.v1"
        or campaign.get("status") != "built_not_submitted"
    ):
        raise ValueError("local water campaign manifest is invalid")
    imported = []
    for product in campaign["products"]:
        product_id = product["product_id"]
        local_case = campaign_root / "bundle" / "cases" / product_id
        case_manifest_path = local_case / "case_manifest.json"
        if _sha256(case_manifest_path) != product["case_manifest_sha256"]:
            raise ValueError(f"{product_id}: local case manifest changed")
        case_manifest = json.loads(case_manifest_path.read_text())
        completions = sorted(remote_results.glob(f"{product_id}/*/case_completion.json"))
        if len(completions) != 1:
            raise ValueError(
                f"{product_id}: expected one remote completion, found {len(completions)}"
            )
        completion_path = completions[0]
        completion = json.loads(completion_path.read_text())
        remote_case = completion_path.parent / "case"
        if (
            completion.get("schema")
            != "nadoc.photoproduct-alpine-water-case-completion.v1"
            or completion.get("status") != "completed_unreviewed"
            or completion.get("product_id") != product_id
            or completion.get("job_count") != case_manifest["job_count"]
            or completion.get("case_manifest_sha256")
            != product["case_manifest_sha256"]
            or _sha256(remote_case / "case_manifest.json")
            != product["case_manifest_sha256"]
        ):
            raise ValueError(f"{product_id}: remote completion provenance is invalid")
        output_records = {
            item["relative_job_dir"]: item for item in completion["outputs"]
        }
        if set(output_records) != {
            item["relative_job_dir"] for item in case_manifest["jobs"]
        }:
            raise ValueError(f"{product_id}: remote output inventory differs")
        for job in case_manifest["jobs"]:
            relative = job["relative_job_dir"]
            local_job = local_case / relative
            remote_job = remote_case / relative
            local_manifest = local_job / "job_manifest.json"
            remote_manifest = remote_job / "job_manifest.json"
            if (
                _sha256(local_manifest) != job["job_manifest_sha256"]
                or _sha256(remote_manifest) != job["job_manifest_sha256"]
                or _sha256(local_job / "input.dat") != job["input_sha256"]
                or _sha256(remote_job / "input.dat") != job["input_sha256"]
            ):
                raise ValueError(f"{product_id} {relative}: input provenance changed")
            remote_output = remote_job / "output.dat"
            expected_output_hash = output_records[relative]["output_sha256"]
            if not remote_output.is_file() or _sha256(remote_output) != expected_output_hash:
                raise ValueError(f"{product_id} {relative}: output is missing or changed")
            local_output = local_job / "output.dat"
            local_run = local_job / "run_manifest.json"
            if local_output.exists() or local_run.exists():
                raise FileExistsError(f"refusing to overwrite local result: {local_job}")
            shutil.copyfile(remote_output, local_output)
            parsed = parse_psi4_output(local_output.read_text(errors="replace"), "water_interaction")
            if not parsed["passed_execution_checks"]:
                raise ValueError(f"{product_id} {relative}: Psi4 execution did not pass")
            run = {
                "schema": "nadoc.photoproduct-qm-run.v1",
                "status": "completed_unreviewed",
                "gate_effect": "none",
                "job_manifest_sha256": job["job_manifest_sha256"],
                "command": [
                    "/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/envs/"
                    "nadoc-qm-1.11/bin/psi4",
                    "input.dat",
                    "output.dat",
                ],
                "scratch_dir": "Alpine SLURM_SCRATCH (ephemeral; removed after job)",
                "returncode": 0,
                "stdout_tail": "",
                "stderr_tail": "",
                "parsed": parsed,
                "outputs": {
                    "output.dat": {
                        "path": str(local_output.resolve()),
                        "sha256": expected_output_hash,
                        "bytes": local_output.stat().st_size,
                    }
                },
                "remote_completion": {
                    "path": str(completion_path.resolve()),
                    "sha256": _sha256(completion_path),
                    "slurm": completion.get("slurm"),
                },
            }
            local_run.write_text(json.dumps(run, indent=2) + "\n")

        site_audits = []
        series_root = local_case / "series"
        for site_dir in sorted(path for path in series_root.iterdir() if path.is_dir()):
            point_dirs = sorted(path for path in site_dir.iterdir() if path.is_dir())
            audit_path = site_dir / "water_series_audit.json"
            audit = audit_water_interaction_series(point_dirs, output_path=audit_path)
            if not audit["passed"]:
                raise ValueError(f"{product_id} {site_dir.name}: water curve audit failed")
            site_audits.append(
                {
                    "site_id": site_dir.name,
                    "path": str(audit_path.resolve()),
                    "sha256": _sha256(audit_path),
                }
            )
        imported.append(
            {
                "product_id": product_id,
                "job_count": case_manifest["job_count"],
                "site_audits": site_audits,
                "remote_completion": {
                    "path": str(completion_path.resolve()),
                    "sha256": _sha256(completion_path),
                },
            }
        )
    report = {
        "schema": "nadoc.photoproduct-alpine-water-collection.v1",
        "status": "passed_import_and_curve_audits",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_count": len(imported),
        "job_count": sum(item["job_count"] for item in imported),
        "products": imported,
        "interpretation": (
            "Passed fixed-geometry QM curve evidence. Joint charge fitting, held-out "
            "metrics, and force-field release remain independent."
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
