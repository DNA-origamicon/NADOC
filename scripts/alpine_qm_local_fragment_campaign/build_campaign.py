#!/usr/bin/env python3
"""Build a relocatable Alpine continuation for the local fragment campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.parameterization.photoproduct_distributed_hessian import (  # noqa: E402
    materialize_frequency_job_provenance,
)
from backend.parameterization.photoproduct_qm import (  # noqa: E402
    generate_psi4_job,
    resolve_frequency_job_reference,
)

REMOTE_ROOT = Path(
    "/scratch/alpine/jojo6687/nadoc_qm_campaigns/"
    "tt-cpd-local-fragment-continuation-v1"
)
PASSED_FREQUENCY = {
    "passed_harmonic_minimum",
    "passed_candidate_harmonic_minimum",
}
HELDOUT_IDS = ("syn-heldout-orientation", "anti-heldout-trans")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def _record(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _completed_frequency(job_dir: Path, expected_manifest_sha: str) -> dict | None:
    audit_path = job_dir / "frequency_audit.json"
    run_path = job_dir / "run_manifest.json"
    if not audit_path.is_file() and not run_path.is_file():
        return None
    if not audit_path.is_file() or not run_path.is_file():
        return None
    audit = _read(audit_path)
    run = _read(run_path)
    if (
        audit.get("status") not in PASSED_FREQUENCY
        or run.get("status") != "completed_unreviewed"
        or run.get("job_manifest_sha256") != expected_manifest_sha
        or audit.get("imaginary_mode_count") != 0
        or audit.get("parsed_mode_count") != audit.get("expected_mode_count")
        or (audit.get("cartesian_hessian") or {}).get("status") != "passed"
    ):
        return None
    for name, output in (run.get("outputs") or {}).items():
        path = job_dir / name
        if not path.is_file() or _sha256(path) != output.get("sha256"):
            raise ValueError(f"completed frequency output changed: {path}")
    return {
        "id": job_dir.parent.name,
        "status": audit["status"],
        "imaginary_mode_count": 0,
        "lowest_frequency_cm_inverse": audit["lowest_frequency_cm_inverse"],
        "frequency_audit": _record(audit_path),
        "run_manifest": _record(run_path),
    }


def _copy_heldouts(local_root: Path, bundle: Path) -> dict[str, object]:
    destination = bundle / "sealed-heldout"
    records = []
    for case_id in HELDOUT_IDS:
        source = local_root / "cases" / case_id
        case_path = source / "case_manifest.json"
        job_path = source / "job/job_manifest.json"
        case = _read(case_path)
        job = _read(job_path)
        if (
            case.get("id") != case_id
            or case.get("status") != "prepared_not_run"
            or job.get("job_kind") != "geometry_optimization"
            or any((source / "job" / name).exists() for name in ("output.dat", "run_manifest.json"))
        ):
            raise ValueError(f"held-out case is not pristine: {case_id}")
        target = destination / case_id
        shutil.copytree(source, target)
        records.append(
            {
                "id": case_id,
                "status": "sealed_waiting_primary_fit_freeze",
                "case_manifest_sha256": _sha256(target / "case_manifest.json"),
                "job_manifest_sha256": _sha256(target / "job/job_manifest.json"),
                "input_sha256": _sha256(target / "job/input.dat"),
            }
        )
    hold = {
        "schema": "nadoc.photoproduct-alpine-heldout-seal.v1",
        "status": "sealed_waiting_primary_fit_freeze",
        "gate_effect": "none",
        "simulation_ready": False,
        "cases": records,
        "release_requirements": [
            "frequency/Hessian cohort passed",
            "reused-core frequency inventory reconciled",
            "charge, nonbonded and torsion targets collected and audited",
            "primary fit and transfer metrics frozen in a hash-pinned receipt",
        ],
        "interpretation": (
            "The held-out inputs are transport-ready but cannot be submitted or "
            "inspected as fit evidence before the freeze receipt exists."
        ),
    }
    (destination / "HOLD.json").write_text(json.dumps(hold, indent=2) + "\n")
    return hold


def build(*, local_root: Path, output_root: Path) -> dict[str, object]:
    local_root = local_root.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite campaign: {output_root}")
    scope_path = local_root / "frequency_scope_v1.json"
    campaign_path = local_root / "campaign_manifest.json"
    scope = _read(scope_path)
    campaign = _read(campaign_path)
    protocol_path = Path(campaign["protocol"]["path"])
    if (
        scope.get("schema") != "nadoc.local-qm-frequency-scope.v1"
        or len(scope.get("jobs") or []) != 7
        or _sha256(protocol_path) != campaign["protocol"]["sha256"]
    ):
        raise ValueError("local frequency scope or protocol is invalid")

    bundle = output_root / "bundle"
    cases_root = bundle / "frequency-cases"
    cases_root.mkdir(parents=True)
    retained = []
    queued = []
    lines = []
    for scoped in scope["jobs"]:
        case_id = scoped["id"]
        source_job_dir = Path(scoped["job_dir"])
        source_manifest_path = source_job_dir / "job_manifest.json"
        expected_sha = scoped["job_manifest"]["sha256"]
        if _sha256(source_manifest_path) != expected_sha:
            raise ValueError(f"source frequency manifest changed: {case_id}")
        completed = _completed_frequency(source_job_dir, expected_sha)
        if completed is not None:
            retained.append(completed)
            continue

        source_job = _read(source_manifest_path)
        source_xyz = resolve_frequency_job_reference(
            job_dir=source_job_dir,
            job=source_job,
            key="source_xyz",
            label="optimized source geometry",
        )
        parent = resolve_frequency_job_reference(
            job_dir=source_job_dir,
            job=source_job,
            key="parent_manifest",
            label="optimized-model parent audit",
        )
        destination = cases_root / case_id / "job"
        alpine_job = generate_psi4_job(
            product_id=source_job["product_id"],
            model_id=source_job["model_id"],
            xyz_path=source_xyz,
            output_dir=destination,
            job_kind="frequency",
            charge=int(source_job["charge"]),
            multiplicity=int(source_job["multiplicity"]),
            atom_map=source_job["atom_map"],
            parent_manifest_path=parent,
            memory_gib=48,
            threads=32,
            protocol_path=protocol_path,
        )
        for key in (
            "product_id",
            "model_id",
            "job_kind",
            "charge",
            "multiplicity",
            "atom_count",
            "method",
            "basis",
            "protocol_version",
            "protocol_sha256",
            "atom_map",
            "expected_outputs",
        ):
            if alpine_job.get(key) != source_job.get(key):
                raise ValueError(f"{case_id}: Alpine job changed scientific field {key}")
        materialize_frequency_job_provenance(job_dir=destination)
        partial_output = source_job_dir / "output.dat"
        source_attempt = None
        if partial_output.is_file():
            source_attempt = {
                "status": "interrupted_preserved_not_restartable",
                "output": _record(partial_output),
                "reuse": "none; clean Alpine rerun required",
            }
        case = {
            "schema": "nadoc.photoproduct-alpine-local-fragment-frequency-case.v1",
            "status": "generated_not_run",
            "gate_effect": "none",
            "simulation_ready": False,
            "id": case_id,
            "product_id": alpine_job["product_id"],
            "model_id": alpine_job["model_id"],
            "atom_count": alpine_job["atom_count"],
            "origin_job_manifest": _record(source_manifest_path),
            "source_local_attempt": source_attempt,
            "job_manifest_sha256": _sha256(destination / "job_manifest.json"),
            "input_sha256": _sha256(destination / "input.dat"),
            "provenance_sha256": _sha256(destination / "frequency_job_provenance.json"),
            "resources": {
                "slurm_cpus": 32,
                "psi4_threads": 32,
                "slurm_memory_gib": 56,
                "psi4_memory_gib": 48,
                "walltime": "23:30:00",
            },
        }
        case_path = destination.parent / "case_manifest.json"
        case_path.write_text(json.dumps(case, indent=2) + "\n")
        case_hash = _sha256(case_path)
        array_index = len(queued)
        lines.append(f"{array_index}\t{case_id}\t{case_hash}")
        queued.append(
            {
                "array_index": array_index,
                "id": case_id,
                "case_manifest_sha256": case_hash,
                "atom_count": alpine_job["atom_count"],
            }
        )

    if len(retained) != 1 or len(queued) != 6:
        raise ValueError(
            f"expected one retained and six queued frequencies; got {len(retained)} and {len(queued)}"
        )
    (bundle / "frequency_cases.tsv").write_text("\n".join(lines) + "\n")
    for name in ("run_case.sh", "frequency.sbatch"):
        shutil.copy2(Path(__file__).with_name(name), bundle / name)
    heldout = _copy_heldouts(local_root, bundle)
    plan = {
        "schema": "nadoc.photoproduct-alpine-local-fragment-offload-plan.v1",
        "status": "frequency_cohort_ready_heldout_sealed",
        "gate_effect": "none",
        "simulation_ready": False,
        "local_execution": "held",
        "stages": [
            {
                "id": "D1-frequency-hessian",
                "status": "ready_for_alpine_submission",
                "payload": "bundle/frequency-cases",
                "completion_trigger": "Slurm array has no active tasks; collect and audit all six results",
                "pass_condition": "all seven scoped minima have 3N-6 real modes and valid Cartesian Hessians",
                "failure_action": "hold all dependent stages",
            },
            {
                "id": "D2-reused-core-frequency-inventory",
                "status": "blocked_by_D1",
                "start_trigger": "gates/frequency_cohort.json reports passed",
                "action": "reconcile five reused core geometries; generate Alpine jobs only for missing matching evidence",
            },
            {
                "id": "D3-charge-nonbonded-torsion-targets",
                "status": "blocked_by_D1_D2_and_scope",
                "start_trigger": "frequency cohort and reused-core inventory pass, then hash-pin target and scan scope",
                "action": "generate and submit all approved target jobs on Alpine",
            },
            {
                "id": "D4-primary-fit-freeze",
                "status": "blocked_by_D3",
                "start_trigger": "all training-target audits pass",
                "completion_trigger": "fit parameters and transfer metrics are frozen in gates/primary_fit_freeze.json",
            },
            {
                "id": "C-heldout-transfer",
                "status": "sealed_waiting_primary_fit_freeze",
                "payload": "bundle/sealed-heldout",
                "start_trigger": "valid hash-pinned primary fit freeze receipt exists",
                "failure_action": "hold release; do not refit against held-out evidence without a new campaign version",
            },
            {
                "id": "E-full-boundary-validation",
                "status": "reuse_existing_alpine_work",
                "external_slurm_job": "32312446",
                "start_trigger": "C transfer decision frozen",
                "action": "collect existing Alpine boundary recovery evidence; do not duplicate it",
            },
        ],
        "heldout_seal": heldout,
    }
    (bundle / "offload_plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    inventory = [
        f"{_sha256(path)}  {path.relative_to(bundle)}"
        for path in sorted(item for item in bundle.rglob("*") if item.is_file())
        if path.name != "MANIFEST.sha256"
    ]
    (bundle / "MANIFEST.sha256").write_text("\n".join(inventory) + "\n")
    archive = output_root / "alpine-local-fragment-continuation-v1.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(bundle, arcname="bundle")
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    checksum.write_text(f"{_sha256(archive)}  {archive.name}\n")
    report = {
        "schema": "nadoc.photoproduct-alpine-local-fragment-campaign.v1",
        "status": "built_not_submitted",
        "gate_effect": "none",
        "simulation_ready": False,
        "source_local_campaign": _record(campaign_path),
        "frequency_scope": _record(scope_path),
        "retained_local_frequencies": retained,
        "queued_frequency_count": len(queued),
        "queued_frequencies": queued,
        "sealed_heldout_count": len(heldout["cases"]),
        "remote_root": str(REMOTE_ROOT),
        "maximum_concurrent_array_tasks": 3,
        "archive": _record(archive),
        "offload_plan": _record(bundle / "offload_plan.json"),
        "interpretation": (
            "This relocatable payload transfers remaining QM execution to Alpine. "
            "It does not advance any parameter or simulation release gate."
        ),
    }
    output_root.mkdir(exist_ok=True)
    (output_root / "campaign_manifest.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-campaign", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                local_root=args.local_campaign,
                output_root=args.output_root,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
