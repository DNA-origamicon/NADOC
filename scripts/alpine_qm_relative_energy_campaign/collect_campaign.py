#!/usr/bin/env python3
"""Import and hash-audit Alpine TT-CPD relative-energy single points."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.parameterization.photoproduct_qm import parse_psi4_output  # noqa: E402

HARTREE_TO_KCAL_MOL = 627.5094740631


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(*, campaign_root: Path, remote_results: Path) -> dict[str, object]:
    report_path = campaign_root / "collection_report.json"
    if report_path.exists():
        raise FileExistsError(f"refusing to overwrite collection report: {report_path}")
    campaign_path = campaign_root / "campaign_manifest.json"
    campaign = json.loads(campaign_path.read_text())
    if campaign.get("schema") != "nadoc.photoproduct-alpine-relative-energy-campaign.v1":
        raise ValueError("local relative-energy campaign manifest is invalid")
    products = []
    for record in campaign["products"]:
        product_id = record["product_id"]
        local_case = campaign_root / "bundle/cases" / product_id
        case_path = local_case / "case_manifest.json"
        if _sha256(case_path) != record["case_manifest_sha256"]:
            raise ValueError(f"{product_id}: local case manifest changed")
        case = json.loads(case_path.read_text())
        completions = sorted(remote_results.glob(f"{product_id}/*/case_completion.json"))
        if len(completions) != 1:
            raise ValueError(f"{product_id}: expected exactly one remote completion")
        completion_path = completions[0]
        completion = json.loads(completion_path.read_text())
        remote_case = completion_path.parent / "case"
        if (
            completion.get("schema")
            != "nadoc.photoproduct-alpine-relative-energy-case-completion.v1"
            or completion.get("status") != "completed_unreviewed"
            or completion.get("product_id") != product_id
            or completion.get("job_count") != case["job_count"]
            or completion.get("case_manifest_sha256") != record["case_manifest_sha256"]
            or _sha256(remote_case / "case_manifest.json") != record["case_manifest_sha256"]
        ):
            raise ValueError(f"{product_id}: remote completion is invalid")
        outputs = {item["point_id"]: item for item in completion["outputs"]}
        if set(outputs) != {item["point_id"] for item in case["jobs"]}:
            raise ValueError(f"{product_id}: remote point inventory differs")
        energies = []
        for job in case["jobs"]:
            point_id = job["point_id"]
            local_job = local_case / job["relative_job_dir"]
            remote_job = remote_case / job["relative_job_dir"]
            local_manifest = local_job / "job_manifest.json"
            remote_manifest = remote_job / "job_manifest.json"
            if (
                _sha256(local_manifest) != job["job_manifest_sha256"]
                or _sha256(remote_manifest) != job["job_manifest_sha256"]
                or _sha256(local_job / "input.dat") != job["input_sha256"]
                or _sha256(remote_job / "input.dat") != job["input_sha256"]
            ):
                raise ValueError(f"{product_id} {point_id}: input provenance changed")
            remote_output = remote_job / "output.dat"
            output_hash = outputs[point_id]["output_sha256"]
            if not remote_output.is_file() or _sha256(remote_output) != output_hash:
                raise ValueError(f"{product_id} {point_id}: output changed")
            local_output = local_job / "output.dat"
            run_path = local_job / "run_manifest.json"
            if local_output.exists() or run_path.exists():
                raise FileExistsError(f"refusing to overwrite result: {local_job}")
            shutil.copyfile(remote_output, local_output)
            parsed = parse_psi4_output(
                local_output.read_text(errors="replace"), "conformer_single_point"
            )
            energy = parsed["final_energy_hartree"]
            if not parsed["passed_execution_checks"] or not isinstance(energy, float) or not math.isfinite(energy):
                raise ValueError(f"{product_id} {point_id}: energy parse failed")
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
                        "sha256": output_hash,
                        "bytes": local_output.stat().st_size,
                    }
                },
                "remote_completion": {
                    "path": str(completion_path.resolve()),
                    "sha256": _sha256(completion_path),
                    "slurm": completion.get("slurm"),
                },
            }
            run_path.write_text(json.dumps(run, indent=2) + "\n")
            energies.append(
                {
                    "point_id": point_id,
                    "energy_hartree": energy,
                    "geometry_sha256": job["geometry_sha256"],
                    "geometry_provenance": job["geometry_provenance"],
                    "output_sha256": output_hash,
                }
            )
        minimum = [item for item in energies if item["point_id"] == "minimum"]
        if len(minimum) != 1:
            raise ValueError(f"{product_id}: unique minimum point is absent")
        baseline = minimum[0]["energy_hartree"]
        for item in energies:
            item["relative_energy_kcal_mol"] = (
                item["energy_hartree"] - baseline
            ) * HARTREE_TO_KCAL_MOL
            item["in_preregistered_low_energy_region"] = (
                item["relative_energy_kcal_mol"] <= 12.0
            )
        target_path = local_case / "relative_energy_targets.json"
        target = {
            "schema": "nadoc.photoproduct-relative-energy-targets.v1",
            "status": "complete_unfitted_targets",
            "gate_effect": "none",
            "simulation_ready": False,
            "product_id": product_id,
            "model_id": case["model_id"],
            "method": case["jobs"][0]["method"],
            "basis": case["jobs"][0]["basis"],
            "low_energy_ceiling_kcal_mol": 12.0,
            "points": energies,
            "sources": {
                "case_manifest": {
                    "path": str(case_path.resolve()),
                    "sha256": _sha256(case_path),
                },
                "remote_completion": {
                    "path": str(completion_path.resolve()),
                    "sha256": _sha256(completion_path),
                },
            },
        }
        target_path.write_text(json.dumps(target, indent=2) + "\n")
        products.append(
            {
                "product_id": product_id,
                "point_count": len(energies),
                "low_energy_point_count": sum(
                    item["in_preregistered_low_energy_region"] for item in energies
                ),
                "targets": {"path": str(target_path), "sha256": _sha256(target_path)},
            }
        )
    report = {
        "schema": "nadoc.photoproduct-alpine-relative-energy-collection.v1",
        "status": "passed_import_and_energy_audit",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_count": len(products),
        "point_count": sum(item["point_count"] for item in products),
        "products": products,
        "source_campaign": {"path": str(campaign_path), "sha256": _sha256(campaign_path)},
        "interpretation": (
            "QM relative-energy targets only. MM comparison and release gates remain."
        ),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--remote-results", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(collect(campaign_root=args.campaign_root.resolve(), remote_results=args.remote_results.resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
