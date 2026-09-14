#!/usr/bin/env python3
"""Continue the canonical cis-syn candidate after local QM responses finish.

This unattended helper is deliberately bounded at non-releasing CHARMM candidate
assets. It never mutates the photoproduct registry or installs candidate parameters.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.parameterization.photoproduct_coupled_conformer import (  # noqa: E402
    build_fixed_geometry_hessian_target_bundle,
)
from backend.parameterization.photoproduct_candidate_assembly import (  # noqa: E402
    assemble_quantitative_parameter_workbook,
)
from backend.parameterization.photoproduct_candidate_engine import (  # noqa: E402
    run_candidate_engine_smoke,
)
from backend.parameterization.photoproduct_charmm_export import (  # noqa: E402
    export_charmm_candidate_assets,
)
from backend.parameterization.photoproduct_fit import (  # noqa: E402
    audit_parameter_workbook,
)
from backend.parameterization.photoproduct_openmm_linear_response import (  # noqa: E402
    build_openmm_linear_response,
)
from backend.parameterization.photoproduct_response_campaign import (  # noqa: E402
    build_openmm_response_campaign,
)
from backend.parameterization.photoproduct_response_fit import (  # noqa: E402
    build_charmm_bonded_transform_candidate,
    evaluate_reviewed_response_fit,
    materialize_quantitative_response_fit_specification,
    select_quantitative_response_fit_candidate,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _passed_batch(path: Path) -> bool:
    if not path.is_file():
        return False
    payload = json.loads(path.read_text())
    return (
        payload.get("schema") == "nadoc.photoproduct-local-fixed-hessian-batch.v1"
        and payload.get("status") == "passed"
        and payload.get("product_id") == "tt-cpd-cis-syn"
    )


def _require_under(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"path is outside the Archive storage root: {resolved}"
        ) from exc
    return resolved


def continue_candidate(args: argparse.Namespace) -> dict[str, Any]:
    storage_root = args.storage_root.resolve()
    work_root = _require_under(args.work_root, storage_root)
    basis = _require_under(args.fit_basis_manifest, storage_root)
    minimum_response = _require_under(args.minimum_response, storage_root)
    output = _require_under(args.output, storage_root)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite continuation report: {output}")
    conformer_dirs = [work_root / f"conformer-{number:03d}" for number in range(1, 5)]
    reports = [path / args.batch_report_name for path in conformer_dirs]
    while not all(_passed_batch(path) for path in reports):
        failed = []
        for path in reports:
            if path.is_file():
                payload = json.loads(path.read_text())
                if payload.get("status") == "failed":
                    failed.append(f"{path}: {payload.get('error')}")
        if failed:
            raise RuntimeError(
                "one or more QM response batches failed: " + "; ".join(failed)
            )
        if args.once:
            return {
                "schema": "nadoc.photoproduct-cis-syn-unattended-continuation.v1",
                "status": "waiting_for_qm",
                "simulation_ready": False,
                "gate_effect": "none",
                "completed_batch_count": sum(_passed_batch(path) for path in reports),
            }
        time.sleep(args.poll_seconds)

    response_paths: dict[str, Path] = {}
    for number, directory in enumerate(conformer_dirs, start=1):
        job_dir = directory / "job"
        target = job_dir / "off_equilibrium_hessian_targets.json"
        if not target.exists():
            build_fixed_geometry_hessian_target_bundle(
                job_dir=job_dir,
                output_path=target,
            )
        response_dir = directory / args.response_dir_name
        response = response_dir / "linear_response_manifest.json"
        if not response.exists():
            build_openmm_linear_response(
                fit_basis_manifest_path=basis,
                hessian_targets_path=target,
                output_dir=response_dir,
            )
        response_paths[f"conformer-{number:03d}"] = response

    fit_root = work_root / args.fit_run_name
    campaign_dir = fit_root / "campaign"
    campaign = campaign_dir / "response_campaign_manifest.json"
    if not campaign.exists():
        build_openmm_response_campaign(
            training_response_paths=[
                minimum_response,
                response_paths["conformer-001"],
                response_paths["conformer-004"],
            ],
            validation_response_paths=[
                response_paths["conformer-002"],
                response_paths["conformer-003"],
            ],
            output_dir=campaign_dir,
        )
    specification = fit_root / "quantitative_fit_specification.json"
    if not specification.exists():
        materialize_quantitative_response_fit_specification(
            campaign_path=campaign,
            output_path=specification,
            policy_path=args.response_fit_policy,
        )
    evaluation_dir = fit_root / "evaluation"
    evaluation = evaluation_dir / "response_fit_evaluation.json"
    if not evaluation.exists():
        evaluate_reviewed_response_fit(
            campaign_path=campaign,
            specification_path=specification,
            output_dir=evaluation_dir,
        )
    selected = fit_root / "selected_response_fit_candidate.json"
    if not selected.exists():
        select_quantitative_response_fit_candidate(
            evaluation_path=evaluation,
            output_path=selected,
            policy_path=args.response_fit_policy,
        )
    transformed = fit_root / "charmm_bonded_transform_candidate.json"
    if not transformed.exists():
        build_charmm_bonded_transform_candidate(
            selected_candidate_path=selected,
            output_path=transformed,
        )
    candidate_root = _require_under(args.candidate_output_root, storage_root)
    candidate_root.mkdir(parents=True, exist_ok=True)
    workbook = candidate_root / "parameter_workbook.json"
    if not workbook.exists():
        assemble_quantitative_parameter_workbook(
            fit_plan_path=args.fit_plan,
            nonbonded_fit_path=args.nonbonded_fit,
            charmm_transform_path=transformed,
            dna_boundary_model_path=args.dna_boundary_model,
            cgenff_topology_path=args.cgenff_topology,
            cgenff_parameters_path=args.cgenff_parameters,
            output_path=workbook,
        )
    workbook_audit = candidate_root / "parameter_workbook_audit.json"
    if not workbook_audit.exists():
        audit = audit_parameter_workbook(workbook)
        if not audit["passed"]:
            raise RuntimeError(
                "assembled parameter workbook failed its completeness audit"
            )
        workbook_audit.write_text(json.dumps(audit, indent=2) + "\n")
    candidate_assets = candidate_root / "charmm_candidate"
    candidate_manifest = candidate_assets / "candidate_manifest.json"
    if not candidate_manifest.exists():
        export_charmm_candidate_assets(
            workbook_path=workbook,
            workbook_audit_path=workbook_audit,
            output_dir=candidate_assets,
        )
    engine_smoke_dir = candidate_root / args.engine_smoke_name
    engine_smoke_report = engine_smoke_dir / "candidate_engine_smoke.json"
    if not engine_smoke_report.exists():
        smoke = run_candidate_engine_smoke(
            candidate_manifest_path=candidate_manifest,
            boundary_manifest_path=args.dna_boundary_model,
            nucleic_topology_path=args.nucleic_topology,
            nucleic_parameters_path=args.nucleic_parameters,
            psfgen_path=args.psfgen,
            namd_path=args.namd,
            output_dir=engine_smoke_dir,
            storage_root=storage_root,
        )
        if not smoke["passed"]:
            raise RuntimeError("real candidate psfgen/NAMD smoke failed")
    else:
        smoke = json.loads(engine_smoke_report.read_text())
        if (
            smoke.get("schema")
            != "nadoc.photoproduct-candidate-engine-smoke.v1"
            or smoke.get("status") != "passed_candidate_engine_smoke_not_released"
            or smoke.get("passed") is not True
            or smoke.get("product_id") != "tt-cpd-cis-syn"
        ):
            raise RuntimeError("existing real candidate psfgen/NAMD smoke is not passed")
    report = {
        "schema": "nadoc.photoproduct-cis-syn-unattended-continuation.v1",
        "status": "candidate_engine_smoke_complete",
        "simulation_ready": False,
        "gate_effect": "none",
        "finished_at": _now(),
        "product_id": "tt-cpd-cis-syn",
        "qm_batch_reports": [_source(path) for path in reports],
        "fit_basis_manifest": _source(basis),
        "minimum_response": _source(minimum_response),
        "conformer_responses": {
            key: _source(path) for key, path in response_paths.items()
        },
        "campaign": _source(campaign),
        "quantitative_specification": _source(specification),
        "evaluation": _source(evaluation),
        "selected_candidate": _source(selected),
        "charmm_transform_candidate": _source(transformed),
        "parameter_workbook": _source(workbook),
        "parameter_workbook_audit": _source(workbook_audit),
        "charmm_candidate_manifest": _source(candidate_manifest),
        "candidate_engine_smoke": _source(engine_smoke_report),
        "release_blockers": [
            "validate MM minima and held-out conformer energies/geometries",
            "pass explicit-solvent DNA-context NAMD validation and matched controls",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--fit-basis-manifest", type=Path, required=True)
    parser.add_argument("--minimum-response", type=Path, required=True)
    parser.add_argument("--response-fit-policy", type=Path, required=True)
    parser.add_argument("--fit-plan", type=Path, required=True)
    parser.add_argument("--nonbonded-fit", type=Path, required=True)
    parser.add_argument("--dna-boundary-model", type=Path, required=True)
    parser.add_argument("--cgenff-topology", type=Path, required=True)
    parser.add_argument("--cgenff-parameters", type=Path, required=True)
    parser.add_argument("--nucleic-topology", type=Path, required=True)
    parser.add_argument("--nucleic-parameters", type=Path, required=True)
    parser.add_argument("--psfgen", type=Path, required=True)
    parser.add_argument("--namd", type=Path, required=True)
    parser.add_argument("--candidate-output-root", type=Path, required=True)
    parser.add_argument(
        "--engine-smoke-name",
        default="engine_smoke",
        help="versioned child directory for the immutable real-engine smoke",
    )
    parser.add_argument("--fit-run-name", default="unattended-fit-n1-n4-v1")
    parser.add_argument(
        "--response-dir-name",
        default="openmm-response-n1-n4-v1",
        help="versioned per-conformer response directory name",
    )
    parser.add_argument(
        "--batch-report-name",
        default="local-batch-report.json",
        help="immutable per-conformer batch report filename to await",
    )
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.poll_seconds < 10 or args.poll_seconds > 600:
        raise ValueError("poll interval must be between 10 and 600 seconds")
    result = continue_candidate(args)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
