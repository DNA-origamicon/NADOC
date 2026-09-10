#!/usr/bin/env python3
"""Prepare durable core jobs and a review watchlist without executing QM."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_campaign import PROTOCOL_PATH, DEFAULT_OUTPUT_ROOT, _record
from backend.parameterization.photoproduct_qm import generate_psi4_job


def prepare(root: Path) -> dict:
    campaign = json.loads((root / "campaign_manifest.json").read_text())
    target = root / "review_preparation.json"
    if target.exists():
        raise FileExistsError(target)
    work = root.parent / "tt-cpd-work-v1"
    jobs = []
    for item in campaign["existing_core_inventory"]:
        if item["state"] == "completed_identity_audit":
            continue
        product = item["product_id"]
        original = Path(item["job_manifest"]["path"])
        old = json.loads(original.read_text())
        source = work / "stereo-candidates-v2" / product
        for key, filename in (("source_xyz", "candidate.xyz"),
                              ("model_manifest", "candidate_manifest.json")):
            if _record(source / filename)["sha256"] != old[key]["sha256"]:
                raise ValueError(f"archived source digest mismatch: {product}/{key}")
        model = json.loads((source / "candidate_manifest.json").read_text())
        for record in model["outputs"].values():
            path = source / Path(record["path"]).name
            if _record(path)["sha256"] != record["sha256"]:
                raise ValueError(f"archived output digest mismatch: {path}")
            record["path"] = str(path)
        case = root / "core-cases" / product
        case.mkdir(parents=True, exist_ok=False)
        model["relocation_parent"] = _record(source / "candidate_manifest.json")
        model_path = case / "model_manifest.json"
        model_path.write_text(json.dumps(model, indent=2) + "\n")
        job_dir = case / "job"
        generate_psi4_job(
            product_id=product, model_id=old["model_id"],
            xyz_path=source / "candidate.xyz", output_dir=job_dir,
            job_kind="geometry_optimization", charge=0, multiplicity=1,
            atom_map=json.loads(Path(model["outputs"]["atom_map"]["path"]).read_text()),
            model_manifest_path=model_path, memory_gib=4, threads=4,
            maximum_geometry_iterations=300, protocol_path=PROTOCOL_PATH,
        )
        jobs.append({"id": product, "stage": "A", "job_dir": str(job_dir),
                     "job_manifest": _record(job_dir / "job_manifest.json"),
                     "original_job": _record(original),
                     "restart_policy": "fresh optimization from identical archived starting XYZ; not interrupted coordinates",
                     "wall_hours": 3})
    for case in campaign["fragment_cases"]:
        jobs.append({"id": case["id"], "stage": "B" if case["tier"] == "primary" else "C",
                     "job_dir": str(Path(case["job_manifest"]["path"]).parent),
                     "job_manifest": case["job_manifest"], "wall_hours": 18})
    review = {"schema": "nadoc.local-qm-review-preparation.v1",
              "campaign": _record(root / "campaign_manifest.json"),
              "gate_effect": "none", "simulation_ready": False,
              "jobs": jobs,
              "deferred_stages": {"D": "Register generated frequency/scan jobs in review_extensions.json after parent audit",
                                  "E": "Register collected Alpine jobs in review_extensions.json; no local duplicate"},
              "observed_receipts": [str(root.parent / "alpine-qm-cis-syn-boundary-optimization-campaign-v1" / "collection_report.json")],
              "benchmarks": ["tt-cpd-cis-anti-ii", "syn-primary-endpoint-1"]}
    target.write_text(json.dumps(review, indent=2) + "\n")
    return review


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    print(json.dumps(prepare(parser.parse_args().campaign_root.resolve()), indent=2))
