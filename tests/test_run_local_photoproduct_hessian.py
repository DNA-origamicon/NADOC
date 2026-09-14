import hashlib
import json
from pathlib import Path

import pytest

from scripts.run_local_photoproduct_hessian import (
    _completion_state,
    _run_task,
    _validate_existing_assembly,
    _validate_storage_root,
    _validate_passed_predecessor,
    _validate_frequency_job_copy,
    _wait_for_passed_predecessor,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path):
    plan = tmp_path / "plan.json"
    task_dir = tmp_path / "tasks" / "0000-reference"
    task_dir.mkdir(parents=True)
    input_path = task_dir / "input.json"
    input_path.write_text("{}\n")
    task = {
        "id": "0000-reference",
        "input": {"path": "tasks/0000-reference/input.json", "sha256": _sha256(input_path)},
        "result": {"path": "tasks/0000-reference/result.json"},
        "run_record": {"path": "tasks/0000-reference/run_record.json"},
    }
    plan.write_text("plan\n")
    return plan, task_dir, task


def test_completion_state_distinguishes_pending_and_valid_complete_pair(tmp_path: Path):
    plan, task_dir, task = _fixture(tmp_path)
    assert _completion_state(plan_path=plan, root=tmp_path, task=task) == "pending"

    result = task_dir / "result.json"
    result.write_text('{"success":true}\n')
    (task_dir / "run_record.json").write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-distributed-hessian-task-run.v1",
                "status": "completed_unreviewed",
                "gate_effect": "none",
                "plan_sha256": _sha256(plan),
                "task_id": task["id"],
                "input_sha256": task["input"]["sha256"],
                "result": {"sha256": _sha256(result)},
            }
        )
    )

    assert _completion_state(plan_path=plan, root=tmp_path, task=task) == "complete"


def test_completion_state_rejects_half_pair_and_changed_result(tmp_path: Path):
    plan, task_dir, task = _fixture(tmp_path)
    result = task_dir / "result.json"
    result.write_text("{}\n")
    with pytest.raises(ValueError, match="incomplete result/run-record pair"):
        _completion_state(plan_path=plan, root=tmp_path, task=task)

    (task_dir / "run_record.json").write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-distributed-hessian-task-run.v1",
                "status": "completed_unreviewed",
                "gate_effect": "none",
                "plan_sha256": _sha256(plan),
                "task_id": task["id"],
                "input_sha256": task["input"]["sha256"],
                "result": {"sha256": "0" * 64},
            }
        )
    )
    with pytest.raises(ValueError, match="not safely resumable"):
        _completion_state(plan_path=plan, root=tmp_path, task=task)


def test_frequency_job_copy_can_relocate_only_with_identical_bytes(tmp_path: Path):
    original = tmp_path / "temporary" / "frequency"
    original.mkdir(parents=True)
    original_manifest = original / "job_manifest.json"
    original_input = original / "input.dat"
    original_manifest.write_text('{"job":"immutable"}\n')
    original_input.write_text("immutable input\n")
    plan = {
        "frequency_job": {
            "path": str(original_manifest),
            "sha256": _sha256(original_manifest),
            "input_sha256": _sha256(original_input),
        }
    }
    archive_copy = tmp_path / "archive" / "frequency"
    archive_copy.mkdir(parents=True)
    (archive_copy / "job_manifest.json").write_bytes(original_manifest.read_bytes())
    (archive_copy / "input.dat").write_bytes(original_input.read_bytes())

    record = _validate_frequency_job_copy(plan=plan, job_dir=archive_copy)

    assert record["relocated"] is True
    assert record["effective_manifest_path"] == str(
        (archive_copy / "job_manifest.json").resolve()
    )
    assert record["declared_manifest_path"] == str(original_manifest)

    (archive_copy / "input.dat").write_text("changed\n")
    with pytest.raises(ValueError, match="byte-identical copy"):
        _validate_frequency_job_copy(plan=plan, job_dir=archive_copy)


def test_existing_assembly_is_revalidated_for_post_assembly_recovery(tmp_path: Path):
    root = tmp_path / "distributed"
    task_dir = root / "tasks" / "0000-reference"
    job_dir = tmp_path / "frequency"
    task_dir.mkdir(parents=True)
    job_dir.mkdir()
    task_input = task_dir / "input.json"
    task_result = task_dir / "result.json"
    task_run = task_dir / "run_record.json"
    task_input.write_text("{}\n")
    task_result.write_text('{"success":true}\n')
    task = {
        "id": "0000-reference",
        "input": {
            "path": "tasks/0000-reference/input.json",
            "sha256": _sha256(task_input),
        },
        "result": {"path": "tasks/0000-reference/result.json"},
        "run_record": {"path": "tasks/0000-reference/run_record.json"},
    }
    plan = {
        "product_id": "tt-cpd-test",
        "model_id": "test-model",
        "task_count": 1,
        "tasks": [task],
    }
    plan_path = root / "distributed_hessian_plan.json"
    plan_path.write_text(json.dumps(plan) + "\n")
    task_run.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-distributed-hessian-task-run.v1",
                "status": "completed_unreviewed",
                "gate_effect": "none",
                "plan_sha256": _sha256(plan_path),
                "task_id": task["id"],
                "input_sha256": task["input"]["sha256"],
                "result": {"sha256": _sha256(task_result)},
            }
        )
        + "\n"
    )
    job_manifest = job_dir / "job_manifest.json"
    output = job_dir / "output.dat"
    hessian = job_dir / "hessian_hartree_per_bohr2.txt"
    result = job_dir / "distributed_qcschema_result.json"
    job_manifest.write_text("{}\n")
    output.write_text("assembled\n")
    hessian.write_text("0.0\n")
    result.write_text("{}\n")
    run_path = job_dir / "run_manifest.json"
    run_path.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-qm-run.v1",
                "status": "completed_unreviewed",
                "gate_effect": "none",
                "job_manifest_sha256": _sha256(job_manifest),
                "distributed_hessian_plan": {"sha256": _sha256(plan_path)},
                "outputs": {
                    path.name: {"sha256": _sha256(path)}
                    for path in (output, hessian, result)
                },
            }
        )
        + "\n"
    )
    assembly_path = root / "distributed_hessian_audit.json"
    assembly_path.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-distributed-hessian-audit.v1",
                "status": "assembled_unreviewed",
                "gate_effect": "none",
                "product_id": plan["product_id"],
                "model_id": plan["model_id"],
                "task_count": 1,
                "tasks": [
                    {
                        "id": task["id"],
                        "input_sha256": _sha256(task_input),
                        "result_sha256": _sha256(task_result),
                        "run_record_sha256": _sha256(task_run),
                    }
                ],
                "hessian": {"path": str(hessian), "sha256": _sha256(hessian)},
                "frequency_job_run_manifest_sha256": _sha256(run_path),
            }
        )
        + "\n"
    )
    recovered = _validate_existing_assembly(
        plan_path=plan_path,
        plan=plan,
        root=root,
        job_dir=job_dir,
    )
    assert recovered["status"] == "assembled_unreviewed"
    task_result.write_text("changed\n")
    with pytest.raises(ValueError, match="not safely resumable"):
        _validate_existing_assembly(
            plan_path=plan_path,
            plan=plan,
            root=root,
            job_dir=job_dir,
        )


def test_task_process_runs_from_its_scratch_directory(monkeypatch, tmp_path: Path):
    plan, task_dir, task = _fixture(tmp_path)
    scratch_root = tmp_path / "archive-scratch"
    observed = {}

    def fake_run(command, *, cwd, env, stdout, stderr, check):
        observed["command"] = command
        observed["cwd"] = cwd
        observed["pythonpath"] = env["PYTHONPATH"]
        result = task_dir / "result.json"
        result.write_text('{"success":true}\n')
        (task_dir / "run_record.json").write_text(
            json.dumps(
                {
                    "schema": "nadoc.photoproduct-distributed-hessian-task-run.v1",
                    "status": "completed_unreviewed",
                    "gate_effect": "none",
                    "plan_sha256": _sha256(plan),
                    "task_id": task["id"],
                    "input_sha256": task["input"]["sha256"],
                    "result": {"sha256": _sha256(result)},
                }
            )
        )
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(
        "scripts.run_local_photoproduct_hessian.subprocess.run", fake_run
    )
    record = _run_task(
        task=task,
        plan_path=plan,
        root=tmp_path,
        qm_python=Path("/fake/qm/python"),
        scratch_root=scratch_root,
        threads=2,
        memory_gib=3,
    )

    expected = (scratch_root / task["id"]).resolve()
    assert observed["cwd"] == expected
    assert expected.is_dir()
    assert observed["command"][observed["command"].index("--scratch-dir") + 1] == str(
        expected
    )
    assert record["working_directory"] == str(expected)


def test_storage_root_rejects_any_path_on_another_tree(tmp_path: Path):
    archive = tmp_path / "archive"
    archive.mkdir()
    record = _validate_storage_root(
        archive,
        paths={"plan": archive / "plan.json", "scratch": archive / "scratch"},
    )
    assert record["root"] == str(archive.resolve())
    assert record["plan"] == str((archive / "plan.json").resolve())

    with pytest.raises(ValueError, match="output must be located under storage root"):
        _validate_storage_root(
            archive,
            paths={"output": tmp_path / "system-volume" / "batch.json"},
        )


def _write_passed_batch_report(path: Path):
    path.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-local-hessian-batch.v1",
                "status": "passed",
                "product_id": "tt-cpd-a",
                "assembly": {"sha256": "1" * 64},
                "frequency_audit": {
                    "status": "passed_candidate_harmonic_minimum",
                    "sha256": "2" * 64,
                },
                "error": None,
            }
        )
    )


def test_predecessor_chain_requires_a_passed_assembly_and_minimum(tmp_path: Path):
    report_path = tmp_path / "batch.json"
    _write_passed_batch_report(report_path)
    record = _validate_passed_predecessor(report_path)
    assert record["product_id"] == "tt-cpd-a"
    assert record["sha256"] == _sha256(report_path)

    report = json.loads(report_path.read_text())
    report["frequency_audit"]["status"] = "failed"
    report_path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="passed assembly/minimum"):
        _validate_passed_predecessor(report_path)


def test_predecessor_chain_waits_for_service_then_validates_report(
    monkeypatch, tmp_path: Path
):
    report_path = tmp_path / "batch.json"
    _write_passed_batch_report(report_path)
    return_codes = iter((0, 0, 3))
    sleeps = []

    def fake_run(*_args, **_kwargs):
        return type("Completed", (), {"returncode": next(return_codes)})()

    monkeypatch.setattr(
        "scripts.run_local_photoproduct_hessian.subprocess.run", fake_run
    )
    monkeypatch.setattr(
        "scripts.run_local_photoproduct_hessian.time.sleep", sleeps.append
    )
    record = _wait_for_passed_predecessor(
        report_path=report_path,
        service="nadoc-predecessor.service",
        poll_seconds=5,
    )
    assert sleeps == [5, 5]
    assert record["status"] == "passed"
