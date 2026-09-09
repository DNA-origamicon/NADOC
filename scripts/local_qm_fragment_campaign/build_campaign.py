#!/usr/bin/env python3
"""Prepare, but never execute, the literature-tiered local TT-CPD QM campaign."""

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

from backend.parameterization.photoproduct_fragments import (  # noqa: E402
    build_single_endpoint_glycosidic_fragment,
)
from backend.parameterization.photoproduct_qm import generate_psi4_job  # noqa: E402


DEFAULT_EVIDENCE_ROOT = Path(
    "/media/jojo/Archive/NADOC_archive/photoproduct_evidence"
)
DEFAULT_OUTPUT_ROOT = (
    DEFAULT_EVIDENCE_ROOT / "tt-cpd-local-fragment-campaign-v1"
)
POLICY_PATH = (
    REPOSITORY_ROOT
    / "backend/data/forcefield/photoproduct_qm_fragment_policy_v1.json"
)
PROTOCOL_PATH = (
    REPOSITORY_ROOT
    / "backend/data/forcefield/photoproduct_qm_protocol_v1.7.0.json"
)


FRAGMENT_CASES = (
    {
        "id": "syn-primary-endpoint-1",
        "product_id": "tt-cpd-cis-syn",
        "retained_endpoint": 1,
        "tier": "primary",
        "need": "fit and validate the first ordered cis-syn glycosidic boundary",
    },
    {
        "id": "syn-primary-endpoint-2",
        "product_id": "tt-cpd-cis-syn",
        "retained_endpoint": 2,
        "tier": "primary",
        "need": "fit and validate the second ordered cis-syn glycosidic boundary",
    },
    {
        "id": "anti-primary-endpoint-1",
        "product_id": "tt-cpd-cis-anti-i",
        "retained_endpoint": 1,
        "tier": "primary",
        "need": "fit and validate the first ordered anti-family glycosidic boundary",
    },
    {
        "id": "anti-primary-endpoint-2",
        "product_id": "tt-cpd-cis-anti-i",
        "retained_endpoint": 2,
        "tier": "primary",
        "need": "fit and validate the second ordered anti-family glycosidic boundary",
    },
    {
        "id": "syn-heldout-orientation",
        "product_id": "tt-cpd-cis-syn-ii",
        "retained_endpoint": 2,
        "tier": "heldout",
        "need": "test transfer to the alternate ordered syn orientation",
    },
    {
        "id": "anti-heldout-trans",
        "product_id": "tt-cpd-trans-anti-i",
        "retained_endpoint": 1,
        "tier": "heldout",
        "need": "test transfer across cis/trans membership of the anti family",
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _source_manifest(evidence_root: Path, product_id: str) -> Path:
    completion = evidence_root / "tt-cpd-work-v1-completions/fit"
    if product_id == "tt-cpd-cis-syn":
        return completion / "cis-syn/dna-boundary-quantitative-screen-v2/chain-b.json"
    if product_id in {"tt-cpd-cis-syn-ii", "tt-cpd-trans-syn-i", "tt-cpd-trans-syn-ii"}:
        return (
            completion
            / "all-forms/dna-boundary-grafts-v1"
            / product_id
            / "screened-chain-b.json"
        )
    return (
        completion
        / "all-forms/dna-boundary-flex-seeds-v1/screened-flexible-seeds"
        / product_id
        / "chain-b/candidate_manifest.json"
    )


def _existing_core_inventory(evidence_root: Path) -> list[dict[str, object]]:
    core_root = evidence_root / "tt-cpd-work-v1/qm/stereo-geometries"
    inventory: list[dict[str, object]] = []
    for product_id in (
        "tt-cpd-cis-anti-i",
        "tt-cpd-cis-anti-ii",
        "tt-cpd-cis-syn-ii",
        "tt-cpd-trans-anti-i",
        "tt-cpd-trans-anti-ii",
        "tt-cpd-trans-syn-i",
        "tt-cpd-trans-syn-ii",
    ):
        job_dir = core_root / product_id
        if product_id == "tt-cpd-trans-syn-i" and (
            core_root / "tt-cpd-trans-syn-i-retry/optimized_model_audit.json"
        ).is_file():
            result_dir = core_root / "tt-cpd-trans-syn-i-retry"
        else:
            result_dir = job_dir
        job_path = job_dir / "job_manifest.json"
        audit_path = result_dir / "optimized_model_audit.json"
        if not job_path.is_file():
            raise FileNotFoundError(f"missing existing core job: {job_path}")
        inventory.append(
            {
                "product_id": product_id,
                "model": "36-atom neutral N1-methyl TT-CPD core",
                "job_manifest": _record(job_path),
                "input": _record(job_dir / "input.dat"),
                "evidence": _record(audit_path) if audit_path.is_file() else None,
                "state": "completed_identity_audit" if audit_path.is_file() else "prepared_not_run",
                "estimated_local_wall_hours": [1.0, 3.0],
                "need": (
                    "existing core geometry can be reused"
                    if audit_path.is_file()
                    else "complete the distinct product-core minimum before fitting or transfer tests"
                ),
            }
        )
    canonical_job = evidence_root / "tt-cpd-work-v1/qm/geometry/job_manifest.json"
    canonical_audit = evidence_root / "tt-cpd-work-v1/qm/geometry/optimized_model_audit.json"
    inventory.append(
        {
            "product_id": "tt-cpd-cis-syn",
            "model": "36-atom neutral N1-methyl TT-CPD core",
            "job_manifest": _record(canonical_job),
            "input": _record(canonical_job.parent / "input.dat"),
            "evidence": _record(canonical_audit),
            "state": "completed_identity_audit",
            "estimated_local_wall_hours": [0.0, 0.0],
            "need": "existing core geometry can be reused",
        }
    )
    inventory.sort(key=lambda item: str(item["product_id"]))
    return inventory


def _write_run_helper(output_root: Path) -> None:
    source = Path(__file__).with_name("run_selected.sh")
    shutil.copy2(source, output_root / "run_selected.sh")
    (output_root / "run_selected.sh").chmod(0o755)


def build(*, evidence_root: Path, output_root: Path) -> dict[str, object]:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite campaign: {output_root}")
    policy = json.loads(POLICY_PATH.read_text())
    protocol = json.loads(PROTOCOL_PATH.read_text())
    if (
        policy.get("schema") != "nadoc.photoproduct-qm-fragment-policy.v1"
        or policy.get("version") != "1.0.0"
        or policy.get("simulation_ready") is not False
        or protocol.get("version") != "1.7.0"
    ):
        raise ValueError("fragment policy or pinned QM protocol is invalid")

    cases_root = output_root / "cases"
    cases_root.mkdir(parents=True)
    cases: list[dict[str, object]] = []
    for order, specification in enumerate(FRAGMENT_CASES, start=1):
        case_dir = cases_root / str(specification["id"])
        source = _source_manifest(evidence_root, str(specification["product_id"]))
        model_dir = case_dir / "model"
        model = build_single_endpoint_glycosidic_fragment(
            source_manifest_path=source,
            retained_endpoint=int(specification["retained_endpoint"]),
            output_dir=model_dir,
        )
        job_dir = case_dir / "job"
        job = generate_psi4_job(
            product_id=str(specification["product_id"]),
            model_id=str(model["model_id"]),
            xyz_path=model_dir / "model.xyz",
            output_dir=job_dir,
            job_kind="geometry_optimization",
            charge=0,
            multiplicity=1,
            atom_map=model["atom_map"],
            model_manifest_path=model_dir / "model_manifest.json",
            memory_gib=12,
            threads=6,
            maximum_geometry_iterations=300,
            protocol_path=PROTOCOL_PATH,
        )
        case = {
            "schema": "nadoc.photoproduct-local-fragment-case.v1",
            "status": "prepared_not_run",
            "gate_effect": "none",
            "simulation_ready": False,
            "priority_order": order,
            **specification,
            "model_id": model["model_id"],
            "atom_count": model["atom_count"],
            "charge": model["formal_charge"],
            "resources": {
                "psi4_memory_gib": job["memory_gib"],
                "psi4_threads": job["threads"],
                "estimated_local_wall_hours": [6.0, 18.0],
                "estimate_basis": "scaled conservatively from completed 36-atom local jobs; benchmark the first primary fragment before scheduling the rest",
            },
            "source_boundary_manifest": _record(source),
            "model_manifest": _record(model_dir / "model_manifest.json"),
            "job_manifest": _record(job_dir / "job_manifest.json"),
            "input": _record(job_dir / "input.dat"),
        }
        case_path = case_dir / "case_manifest.json"
        case_path.write_text(json.dumps(case, indent=2) + "\n")
        cases.append({**case, "case_manifest": _record(case_path)})

    output_root.mkdir(parents=True, exist_ok=True)
    _write_run_helper(output_root)
    core = _existing_core_inventory(evidence_root)
    missing_core = [item for item in core if item["state"] == "prepared_not_run"]
    primary_cases = [item for item in cases if item["tier"] == "primary"]
    heldout_cases = [item for item in cases if item["tier"] == "heldout"]
    campaign = {
        "schema": "nadoc.photoproduct-local-fragment-campaign.v1",
        "version": "1.0.0",
        "status": "prepared_not_run",
        "gate_effect": "none",
        "simulation_ready": False,
        "storage_root": str(output_root.resolve()),
        "execution_started": False,
        "alpine_boundary_job_action": "leave_submitted_job_unchanged; collect it if it runs and treat it as optional full-boundary validation",
        "policy": _record(POLICY_PATH),
        "protocol": _record(PROTOCOL_PATH),
        "existing_core_inventory": core,
        "fragment_cases": cases,
        "decision_batches": [
            {
                "id": "A-missing-core-minima",
                "need": "complete the three distinct core stereoisomers that have no passed optimized-model audit",
                "jobs": [item["product_id"] for item in missing_core],
                "job_count": len(missing_core),
                "estimated_sequential_local_wall_hours": [
                    sum(item["estimated_local_wall_hours"][0] for item in missing_core),
                    sum(item["estimated_local_wall_hours"][1] for item in missing_core),
                ],
            },
            {
                "id": "B-primary-glycosidic-boundaries",
                "need": "fit both ordered sugar interfaces for the syn and anti parameter families",
                "jobs": [item["id"] for item in primary_cases],
                "job_count": len(primary_cases),
                "estimated_sequential_local_wall_hours": [24.0, 72.0],
            },
            {
                "id": "C-heldout-transfer-boundaries",
                "need": "test whether the primary family terms transfer before expanding to more full-boundary QM",
                "jobs": [item["id"] for item in heldout_cases],
                "job_count": len(heldout_cases),
                "estimated_sequential_local_wall_hours": [12.0, 36.0],
            },
            {
                "id": "D-dependent-frequency-and-torsion-targets",
                "need": "generate frequencies and selected glycosidic scans only from passed optimized fragment minima",
                "jobs": [],
                "job_count": 0,
                "state": "not_generatable_until_parent_minima_exist",
                "estimated_sequential_local_wall_hours": [40.0, 140.0],
                "note": "This is deliberately not precomputed from non-minimum starting coordinates.",
            },
        ],
        "recommended_first_choice": {
            "batch": "A-missing-core-minima",
            "first_job": "tt-cpd-cis-anti-ii",
            "reason": "smallest missing evidence, low local resource risk, and required regardless of later boundary-sharing decisions",
        },
        "release_effect": "none; all force-field and NAMD production gates remain closed",
    }
    manifest_path = output_root / "campaign_manifest.json"
    manifest_path.write_text(json.dumps(campaign, indent=2) + "\n")
    return campaign


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    campaign = build(
        evidence_root=args.evidence_root.resolve(),
        output_root=args.output_root.resolve(),
    )
    print(json.dumps(campaign, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
