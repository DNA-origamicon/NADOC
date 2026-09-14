from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.alpine_qm_campaign.collect_campaign import import_campaign_results
from scripts.alpine_qm_campaign.repair_case_completions import (
    repair_case_completions,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan(root: Path) -> tuple[Path, dict]:
    task_dir = root / "tasks/0000-reference"
    task_dir.mkdir(parents=True)
    input_path = task_dir / "input.json"
    input_path.write_text('{"driver":"gradient"}\n')
    task = {
        "id": "0000-reference",
        "label": "reference",
        "driver": "gradient",
        "input": {"path": "tasks/0000-reference/input.json", "sha256": _sha(input_path)},
        "result": {"path": "tasks/0000-reference/result.json"},
        "run_record": {"path": "tasks/0000-reference/run_record.json"},
    }
    path = root / "distributed_hessian_plan.json"
    path.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-distributed-hessian-plan.v1",
                "status": "prepared_not_run",
                "gate_effect": "none",
                "product_id": "tt-cpd-test",
                "model_id": "model",
                "task_count": 1,
                "tasks": [task],
            },
            indent=2,
        )
        + "\n"
    )
    return path, task


def test_import_campaign_results_requires_receipts_and_identical_plans(tmp_path):
    destination, _ = _plan(
        tmp_path / "work/tt-cpd-test/conformer-001/distributed"
    )
    source, task = _plan(
        tmp_path / "remote/tt-cpd-test/conformer-001/123_0/case/distributed"
    )
    assert source.read_bytes() == destination.read_bytes()
    source_task = source.parent / "tasks/0000-reference"
    result = source_task / "result.json"
    result.write_text('{"success":true}\n')
    run = source_task / "run_record.json"
    run.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-distributed-hessian-task-run.v1",
                "status": "completed_unreviewed",
                "gate_effect": "none",
                "plan_sha256": _sha(source),
                "task_id": task["id"],
                "input_sha256": task["input"]["sha256"],
                "result": {"sha256": _sha(result)},
            }
        )
        + "\n"
    )
    completion = source.parents[2] / "case_completion.json"
    completion.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-alpine-qm-case.v1",
                "status": "completed_unreviewed",
                "gate_effect": "none",
                "product_id": "tt-cpd-test",
                "conformer_id": "conformer-001",
                "task_count": 1,
                "plan_sha256": _sha(source),
                "tasks": [
                    {
                        "task_id": task["id"],
                        "result_sha256": _sha(result),
                        "run_sha256": _sha(run),
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    campaign = tmp_path / "campaign.json"
    campaign.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-alpine-qm-campaign.v1",
                "status": "prepared_not_submitted",
                "gate_effect": "none",
                "case_count": 1,
                "cases": [
                    {
                        "product_id": "tt-cpd-test",
                        "conformer_id": "conformer-001",
                        "task_count": 1,
                        "plan_sha256": _sha(source),
                    }
                ],
            }
        )
        + "\n"
    )

    report = import_campaign_results(
        campaign_manifest_path=campaign,
        remote_results_root=tmp_path / "remote",
        work_root=tmp_path / "work",
        output_path=tmp_path / "import.json",
    )

    assert report["status"] == "complete_task_pairs_imported"
    assert report["case_count"] == 1
    assert report["task_count"] == 1
    copied = destination.parent / "tasks/0000-reference/result.json"
    assert copied.read_bytes() == result.read_bytes()


def test_repair_case_completions_recovers_only_a_missing_case_receipt(tmp_path):
    source, task = _plan(
        tmp_path / "results/tt-cpd-test/conformer-001/123_0/case/distributed"
    )
    task_root = source.parent / "tasks/0000-reference"
    result = task_root / "result.json"
    result.write_text('{"success":true}\n')
    run = task_root / "run_record.json"
    run.write_text(
        json.dumps(
            {
                "status": "completed_unreviewed",
                "plan_sha256": _sha(source),
                "task_id": task["id"],
                "result": {"sha256": _sha(result)},
            }
        )
        + "\n"
    )
    campaign = tmp_path / "campaign.json"
    campaign.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-alpine-qm-campaign.v1",
                "status": "prepared_not_submitted",
                "case_count": 1,
                "cases": [
                    {
                        "product_id": "tt-cpd-test",
                        "conformer_id": "conformer-001",
                        "task_count": 1,
                        "plan_sha256": _sha(source),
                    }
                ],
            }
        )
        + "\n"
    )

    report = repair_case_completions(
        campaign_manifest_path=campaign,
        results_root=tmp_path / "results",
        output_path=tmp_path / "repair.json",
    )

    completion = source.parents[2] / "case_completion.json"
    payload = json.loads(completion.read_text())
    assert report["repaired_count"] == 1
    assert payload["status"] == "completed_unreviewed"
    assert payload["slurm"]["postcompute_receipt_recovered"] is True
    assert payload["tasks"][0]["result_sha256"] == _sha(result)


def test_alpine_runner_syncs_before_receipt_and_watcher_uses_array_job_ids():
    scripts = Path(__file__).parents[1] / "scripts/alpine_qm_campaign"
    runner = (scripts / "run_case.sh").read_text()
    watcher = (scripts / "watch_and_collect.sh").read_text()

    assert runner.index("sync_results\n\nexport result_root") < runner.index(
        '"$qm_python" - <<\'PY\''
    )
    assert "-o JobID,State,ExitCode" in watcher
    assert "-o JobIDRaw,State,ExitCode" not in watcher
