#!/usr/bin/env python3
"""Import Alpine fragment-frequency results and fire the D1 assessment gate."""

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
    audit_frequency_result,
    parse_psi4_output,
)

PASSED_FREQUENCY = {
    "passed_harmonic_minimum",
    "passed_candidate_harmonic_minimum",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def collect(*, campaign_root: Path, remote_results: Path) -> dict[str, object]:
    report_path = campaign_root / "frequency_collection_report.json"
    if report_path.exists():
        raise FileExistsError(f"refusing to overwrite collection report: {report_path}")
    campaign_path = campaign_root / "campaign_manifest.json"
    campaign = _read(campaign_path)
    records = campaign.get("queued_frequencies") or []
    if (
        campaign.get("schema")
        != "nadoc.photoproduct-alpine-local-fragment-campaign.v1"
        or campaign.get("queued_frequency_count") != len(records)
        or not records
    ):
        raise ValueError("local Alpine fragment campaign manifest is invalid")

    required = ("output.dat", "hessian_hartree_per_bohr2.txt")
    results = []
    for record in records:
        case_id = record["id"]
        local_case = campaign_root / "bundle/frequency-cases" / case_id
        local_job = local_case / "job"
        case_path = local_case / "case_manifest.json"
        case = _read(case_path)
        if _sha256(case_path) != record["case_manifest_sha256"]:
            raise ValueError(f"{case_id}: local case manifest changed")
        completions = sorted(remote_results.glob(f"{case_id}/*/case_completion.json"))
        if len(completions) != 1:
            results.append(
                {
                    "id": case_id,
                    "status": "missing_or_ambiguous_completion",
                    "completion_count": len(completions),
                }
            )
            continue
        completion_path = completions[0]
        completion = _read(completion_path)
        remote_case = completion_path.parent / "case"
        remote_job = remote_case / "job"
        valid_receipt = (
            completion.get("schema")
            == "nadoc.photoproduct-alpine-local-fragment-frequency-case-completion.v1"
            and completion.get("id") == case_id
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
            and (remote_job / "frequency_job_provenance.json").is_file()
            and _sha256(remote_job / "frequency_job_provenance.json")
            == case["provenance_sha256"]
        )
        if not valid_receipt:
            results.append({"id": case_id, "status": "invalid_completion_receipt"})
            continue
        if completion.get("status") != "completed_unreviewed":
            results.append(
                {
                    "id": case_id,
                    "status": "frequency_failed_preserved",
                    "returncode": completion.get("returncode"),
                    "completion_sha256": _sha256(completion_path),
                }
            )
            continue
        outputs = completion.get("outputs") or {}
        if any(
            not (remote_job / name).is_file()
            or _sha256(remote_job / name) != (outputs.get(name) or {}).get("sha256")
            for name in required
        ):
            results.append({"id": case_id, "status": "output_hash_mismatch"})
            continue
        if any(
            (local_job / name).exists()
            for name in (*required, "run_manifest.json", "frequency_audit.json")
        ):
            raise FileExistsError(f"refusing to overwrite imported result: {local_job}")
        for name in required:
            shutil.copyfile(remote_job / name, local_job / name)
        parsed = parse_psi4_output(
            (local_job / "output.dat").read_text(errors="replace"), "frequency"
        )
        run = {
            "schema": "nadoc.photoproduct-qm-run.v1",
            "status": (
                "completed_unreviewed" if parsed["passed_execution_checks"] else "failed"
            ),
            "gate_effect": "none",
            "job_manifest_sha256": case["job_manifest_sha256"],
            "command": [
                "/scratch/alpine/jojo6687/nadoc_qm_benchmarks/v1/"
                "envs/nadoc-qm-1.11/bin/psi4",
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
            results.append({"id": case_id, "status": "output_parse_failed"})
            continue
        audit = audit_frequency_result(local_job)
        results.append(
            {
                "id": case_id,
                "status": audit["status"],
                "imaginary_mode_count": audit["imaginary_mode_count"],
                "lowest_frequency_cm_inverse": audit[
                    "lowest_frequency_cm_inverse"
                ],
                "frequency_audit_sha256": _sha256(
                    local_job / "frequency_audit.json"
                ),
            }
        )

    retained = campaign.get("retained_local_frequencies") or []
    passed_remote = sum(item["status"] in PASSED_FREQUENCY for item in results)
    passed_retained = sum(item["status"] in PASSED_FREQUENCY for item in retained)
    all_passed = (
        passed_remote == len(results) == len(records)
        and passed_retained == len(retained)
    )
    stage_id = campaign.get("stage_id", "D1-frequency-hessian")
    next_stage = campaign.get(
        "next_stage", "D2-reused-core-frequency-inventory"
    )
    report = {
        "schema": "nadoc.photoproduct-alpine-local-fragment-frequency-collection.v1",
        "status": "passed_frequency_cohort" if all_passed else "incomplete_or_failed",
        "gate_effect": "none",
        "simulation_ready": False,
        "stage": stage_id,
        "scoped_frequency_count": len(records) + len(retained),
        "passed_frequency_count": passed_remote + passed_retained,
        "retained_local": retained,
        "alpine_results": results,
        "source_campaign": {
            "path": str(campaign_path.resolve()),
            "sha256": _sha256(campaign_path),
        },
        "next_action": (
            campaign.get("passed_next_action", "reconcile reused-core frequency inventory")
            if all_passed
            else "hold dependent stages and review failed or missing cases"
        ),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    gates = campaign_root / "gates"
    gates.mkdir(exist_ok=True)
    gate = {
        "schema": "nadoc.photoproduct-alpine-stage-trigger.v1",
        "stage": stage_id,
        "status": "passed" if all_passed else "hold",
        "gate_effect": "none",
        "simulation_ready": False,
        "assessment": {
            "path": str(report_path.resolve()),
            "sha256": _sha256(report_path),
        },
        "next_stage": next_stage if all_passed else None,
    }
    trigger_file = campaign.get("trigger_file", "frequency_cohort.json")
    if Path(trigger_file).name != trigger_file:
        raise ValueError("trigger file must be a plain filename")
    (gates / trigger_file).write_text(json.dumps(gate, indent=2) + "\n")
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
