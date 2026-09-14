from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import numpy as np
import pytest

from backend.parameterization.photoproduct_distributed_hessian import (
    _configure_psi4_scratch,
    _validated_frequency_job,
    checkpoint_distributed_hessian_pairs,
    materialize_frequency_job_provenance,
    prepare_distributed_hessian,
    reconcile_equivalent_distributed_hessian_pairs,
)
from backend.parameterization.photoproduct_qm import (
    audit_frequency_result,
    generate_psi4_job,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "scripts/photoproduct_workflow.py"
QM_PYTHON = Path("/home/jojo/miniforge3/envs/nadoc-qm/bin/python")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frequency_job(tmp_path: Path) -> Path:
    source = tmp_path / "water.xyz"
    source.write_text(
        "3\nsmall nonlinear distributed-Hessian integration model\n"
        "O  0.000000000000  0.000000000000  0.000000000000\n"
        "H  0.000000000000  0.000000000000  0.957200000000\n"
        "H  0.926627206485  0.000000000000 -0.239987208409\n"
    )
    parent = tmp_path / "optimized_model_audit.json"
    parent.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-optimized-model-audit.v1",
                "status": "passed_identity_and_chirality",
                "product_id": "tt-cpd-cis-syn",
                "model_id": "distributed-hessian-water-test",
                "optimized_xyz": {"path": str(source), "sha256": _sha(source)},
            }
        )
    )
    job_dir = tmp_path / "frequency"
    generate_psi4_job(
        product_id="tt-cpd-cis-syn",
        model_id="distributed-hessian-water-test",
        xyz_path=source,
        output_dir=job_dir,
        job_kind="frequency",
        charge=0,
        multiplicity=1,
        atom_map=["1:O", "1:H1", "1:H2"],
        parent_manifest_path=parent,
        memory_gib=1,
        threads=1,
    )
    return job_dir


def test_distributed_hessian_rejects_changed_frequency_input_before_qm_import(
    tmp_path, monkeypatch
):
    job_dir = _frequency_job(tmp_path)
    (job_dir / "input.dat").write_text("changed\n")

    def unexpected_import():  # pragma: no cover - called only on regression
        raise AssertionError("QM stack should not be imported after a hash failure")

    monkeypatch.setattr(
        "backend.parameterization.photoproduct_distributed_hessian._require_qm_stack",
        unexpected_import,
    )
    with pytest.raises(ValueError, match="input digest"):
        prepare_distributed_hessian(
            job_dir=job_dir, output_dir=tmp_path / "distributed"
        )


def test_frequency_job_provenance_copy_survives_original_path_removal(tmp_path):
    job_dir = _frequency_job(tmp_path)
    job = json.loads((job_dir / "job_manifest.json").read_text())
    source = Path(job["source_xyz"]["path"])
    parent = Path(job["parent_manifest"]["path"])

    relocation = materialize_frequency_job_provenance(job_dir=job_dir)

    assert relocation["status"] == "materialized_byte_identical"
    assert relocation["gate_effect"] == "none"
    source.unlink()
    parent.unlink()
    validated, resolved_source, _protocol = _validated_frequency_job(job_dir)
    assert validated["product_id"] == "tt-cpd-cis-syn"
    assert resolved_source == (job_dir / "provenance/source_geometry.xyz").resolve()
    with pytest.raises(FileExistsError, match="overwrite"):
        materialize_frequency_job_provenance(job_dir=job_dir)


def test_frequency_job_provenance_can_recover_from_hashed_relocated_sources(tmp_path):
    job_dir = _frequency_job(tmp_path)
    job = json.loads((job_dir / "job_manifest.json").read_text())
    source = Path(job["source_xyz"]["path"])
    parent = Path(job["parent_manifest"]["path"])
    archive = tmp_path / "archive"
    archive.mkdir()
    relocated_source = archive / "optimized.xyz"
    relocated_parent = archive / "optimized_model_audit.json"
    relocated_source.write_bytes(source.read_bytes())
    relocated_parent.write_bytes(parent.read_bytes())
    source.unlink()
    parent.unlink()

    relocation = materialize_frequency_job_provenance(
        job_dir=job_dir,
        source_xyz_fallback=relocated_source,
        parent_manifest_fallback=relocated_parent,
    )

    assert relocation["references"]["source_xyz"]["original_path"] == str(source)
    validated, resolved_source, _protocol = _validated_frequency_job(job_dir)
    assert validated["product_id"] == "tt-cpd-cis-syn"
    assert resolved_source == (job_dir / "provenance/source_geometry.xyz").resolve()


def test_frequency_job_provenance_rejects_changed_relocated_source(tmp_path):
    job_dir = _frequency_job(tmp_path)
    job = json.loads((job_dir / "job_manifest.json").read_text())
    source = Path(job["source_xyz"]["path"])
    parent = Path(job["parent_manifest"]["path"])
    relocated_source = tmp_path / "changed.xyz"
    relocated_source.write_text("changed\n")
    source.unlink()

    with pytest.raises(ValueError, match="source geometry is missing or hash-mismatched"):
        materialize_frequency_job_provenance(
            job_dir=job_dir,
            source_xyz_fallback=relocated_source,
            parent_manifest_fallback=parent,
        )


def test_frequency_job_provenance_can_be_materialized_after_execution(tmp_path):
    job_dir = _frequency_job(tmp_path)
    (job_dir / "output.dat").write_text("completed output\n")
    (job_dir / "run_manifest.json").write_text('{"status":"completed"}\n')

    relocation = materialize_frequency_job_provenance(job_dir=job_dir)

    assert relocation["status"] == "materialized_byte_identical"
    with pytest.raises(FileExistsError, match="execution evidence"):
        _validated_frequency_job(job_dir)


def test_psi4_psio_scratch_is_explicitly_pinned(monkeypatch, tmp_path):
    class Manager:
        path = "/tmp"

        def set_default_path(self, value):
            self.path = value

        def get_default_path(self):
            return self.path

    manager = Manager()

    class IOManager:
        @staticmethod
        def shared_object():
            return manager

    class Core:
        pass

    Core.IOManager = IOManager

    class Psi4:
        pass

    Psi4.core = Core
    scratch = tmp_path / "archive-scratch"
    scratch.mkdir()
    monkeypatch.delenv("PSI_SCRATCH", raising=False)

    observed = _configure_psi4_scratch(Psi4, scratch)

    assert observed == scratch.resolve()
    assert manager.path == str(scratch.resolve())
    assert os.environ["PSI_SCRATCH"] == str(scratch.resolve())


def _checkpoint_plan(root: Path) -> tuple[Path, dict]:
    task_dir = root / "tasks/0000-reference"
    task_dir.mkdir(parents=True)
    input_path = task_dir / "input.json"
    input_path.write_text('{"driver":"gradient"}\n')
    task = {
        "id": "0000-reference",
        "label": "reference",
        "driver": "gradient",
        "input": {
            "path": "tasks/0000-reference/input.json",
            "sha256": _sha(input_path),
        },
        "result": {"path": "tasks/0000-reference/result.json"},
        "run_record": {"path": "tasks/0000-reference/run_record.json"},
    }
    plan = root / "distributed_hessian_plan.json"
    plan.write_text(
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
    return plan, task


def test_checkpoint_copies_only_complete_pairs_into_identical_plan(tmp_path):
    source_plan, task = _checkpoint_plan(tmp_path / "source")
    destination_plan, _destination_task = _checkpoint_plan(tmp_path / "destination")
    assert source_plan.read_bytes() == destination_plan.read_bytes()
    source_task = source_plan.parent / "tasks/0000-reference"
    result = source_task / "result.json"
    result.write_text('{"success":true}\n')
    run = source_task / "run_record.json"
    run.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-distributed-hessian-task-run.v1",
                "status": "completed_unreviewed",
                "gate_effect": "none",
                "plan_sha256": _sha(source_plan),
                "task_id": task["id"],
                "input_sha256": task["input"]["sha256"],
                "result": {"sha256": _sha(result)},
            }
        )
        + "\n"
    )

    report = checkpoint_distributed_hessian_pairs(
        source_plan_path=source_plan,
        destination_plan_path=destination_plan,
        output_path=tmp_path / "checkpoint-1.json",
    )

    assert report["copied_pair_count"] == 1
    assert report["reused_pair_count"] == 0
    assert report["pending_pair_count"] == 0
    destination_task = destination_plan.parent / "tasks/0000-reference"
    assert (destination_task / "result.json").read_bytes() == result.read_bytes()
    assert (destination_task / "run_record.json").read_bytes() == run.read_bytes()

    repeated = checkpoint_distributed_hessian_pairs(
        source_plan_path=source_plan,
        destination_plan_path=destination_plan,
        output_path=tmp_path / "checkpoint-2.json",
    )
    assert repeated["copied_pair_count"] == 0
    assert repeated["reused_pair_count"] == 1


def test_checkpoint_rejects_different_or_half_destination(tmp_path):
    source_plan, _task = _checkpoint_plan(tmp_path / "source")
    destination_plan, _destination_task = _checkpoint_plan(tmp_path / "destination")
    destination_plan.write_text(destination_plan.read_text() + " ")
    with pytest.raises(ValueError, match="distinct identical plans"):
        checkpoint_distributed_hessian_pairs(
            source_plan_path=source_plan,
            destination_plan_path=destination_plan,
            output_path=tmp_path / "different.json",
        )

    destination_plan.write_bytes(source_plan.read_bytes())
    half = destination_plan.parent / "tasks/0000-reference/result.json"
    half.write_text('{"success":true}\n')
    with pytest.raises(ValueError, match="incomplete result/run-record pair"):
        checkpoint_distributed_hessian_pairs(
            source_plan_path=source_plan,
            destination_plan_path=destination_plan,
            output_path=tmp_path / "half.json",
        )


def _policy_rollover_plan(root: Path, policy_sha: str) -> tuple[Path, dict]:
    review = root / "screened.json"
    review_payload = {
        "schema": "nadoc.photoproduct-coupled-conformer-plan.v1",
        "status": "quantitatively_screened",
        "product_id": "tt-cpd-trans-syn-i",
        "model_id": "model",
        "conformers": [{"id": "conformer-001", "partition": "training"}],
        "quantitative_screening": {
            "policy": "proper-rotation-coupled-response-v1",
            "policy_source": {"path": "/policy.json", "sha256": policy_sha},
        },
    }
    review.parent.mkdir(parents=True, exist_ok=True)
    review.write_text(json.dumps(review_payload, indent=2) + "\n")
    job = root / "job/job_manifest.json"
    job.parent.mkdir(parents=True)
    job_input = job.parent / "input.dat"
    job_input.write_text("identical psi4 input\n")
    job_payload = {
        "schema": "nadoc.photoproduct-qm-job.v1",
        "status": "generated_not_run",
        "product_id": "tt-cpd-trans-syn-i",
        "model_id": "model",
        "job_kind": "fixed_geometry_hessian",
        "method": "mp2",
        "basis": "6-31G(d)",
        "atom_count": 1,
        "atom_map": ["1:C5"],
        "conformer": {"id": "conformer-001", "partition": "training"},
        "input": {"path": str(job_input), "sha256": _sha(job_input)},
        "coupled_conformer_plan": {"path": str(review), "sha256": _sha(review)},
    }
    job.write_text(json.dumps(job_payload, indent=2) + "\n")
    distributed = root / "distributed"
    task_dir = distributed / "tasks/0000-reference"
    task_dir.mkdir(parents=True)
    task_input = task_dir / "input.json"
    task_input.write_text('{"driver":"gradient","molecule":"same"}\n')
    task = {
        "id": "0000-reference",
        "label": "reference",
        "driver": "gradient",
        "input": {"path": "tasks/0000-reference/input.json", "sha256": _sha(task_input)},
        "result": {"path": "tasks/0000-reference/result.json"},
        "run_record": {"path": "tasks/0000-reference/run_record.json"},
    }
    plan = distributed / "distributed_hessian_plan.json"
    plan_payload = {
        "schema": "nadoc.photoproduct-distributed-hessian-plan.v1",
        "status": "prepared_not_run",
        "gate_effect": "none",
        "job_kind": "fixed_geometry_hessian",
        "product_id": "tt-cpd-trans-syn-i",
        "model_id": "model",
        "conformer": {"id": "conformer-001", "partition": "training"},
        "method": "mp2",
        "basis": "6-31G(d)",
        "atom_count": 1,
        "atom_map": ["1:C5"],
        "fixed_geometry_hessian_job": {
            "path": str(job),
            "sha256": _sha(job),
            "input_sha256": _sha(job_input),
        },
        "reviewed_coupled_conformer_plan": {"path": str(review), "sha256": _sha(review)},
        "task_count": 1,
        "tasks": [task],
    }
    plan.write_text(json.dumps(plan_payload, indent=2) + "\n")
    return plan, task


def test_policy_rollover_reconciliation_rebinds_only_identical_qcschema(tmp_path):
    source_plan, task = _policy_rollover_plan(tmp_path / "old", "old-policy")
    destination_plan, _ = _policy_rollover_plan(tmp_path / "new", "new-policy")
    source_task = source_plan.parent / "tasks/0000-reference"
    result = source_task / "result.json"
    result.write_text('{"success":true,"return_result":[0.0]}\n')
    run = source_task / "run_record.json"
    run.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-distributed-hessian-task-run.v1",
                "status": "completed_unreviewed",
                "gate_effect": "none",
                "plan_sha256": _sha(source_plan),
                "task_id": task["id"],
                "input_sha256": task["input"]["sha256"],
                "result": {"path": str(result), "sha256": _sha(result)},
                "execution": {"host": "old-node"},
            },
            indent=2,
        )
        + "\n"
    )

    report = reconcile_equivalent_distributed_hessian_pairs(
        source_plan_path=source_plan,
        destination_plan_path=destination_plan,
        output_path=tmp_path / "reconciliation.json",
    )

    assert report["status"] == "completed_results_reused_after_policy_rollover"
    assert report["copied_pair_count"] == 1
    assert report["policy_transition"] == {
        "source_sha256": "old-policy",
        "destination_sha256": "new-policy",
    }
    destination_task = destination_plan.parent / "tasks/0000-reference"
    rebound = json.loads((destination_task / "run_record.json").read_text())
    assert rebound["plan_sha256"] == _sha(destination_plan)
    assert rebound["execution"] == {"host": "old-node"}
    assert (
        rebound["provenance_reconciliation"]["status"]
        == "reused_byte_identical_qcschema_result"
    )


def test_policy_rollover_reconciliation_rejects_changed_scientific_input(tmp_path):
    source_plan, _ = _policy_rollover_plan(tmp_path / "old", "old-policy")
    destination_plan, _ = _policy_rollover_plan(tmp_path / "new", "new-policy")
    destination_input = destination_plan.parent / "tasks/0000-reference/input.json"
    destination_input.write_text('{"driver":"gradient","molecule":"changed"}\n')
    destination = json.loads(destination_plan.read_text())
    destination["tasks"][0]["input"]["sha256"] = _sha(destination_input)
    destination_plan.write_text(json.dumps(destination, indent=2) + "\n")

    with pytest.raises(ValueError, match="distributed plans differ"):
        reconcile_equivalent_distributed_hessian_pairs(
            source_plan_path=source_plan,
            destination_plan_path=destination_plan,
            output_path=tmp_path / "reconciliation.json",
        )


@pytest.mark.slow
def test_real_psi4_distributed_hessian_round_trip(tmp_path):
    if not QM_PYTHON.is_file():
        pytest.skip("pinned nadoc-qm Python is not installed")
    job_dir = _frequency_job(tmp_path)
    distributed = job_dir / "distributed"

    def run(*arguments: str) -> None:
        completed = subprocess.run(
            [
                str(QM_PYTHON),
                str(WORKFLOW),
                "--storage-root",
                str(tmp_path),
                *arguments,
            ],
            # Psi4 writes timer.dat beside the invoking process even when PSIO
            # scratch is pinned. Keep integration-test housekeeping on the same
            # Archive-backed pytest tree as every generated job and task.
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

    run(
        "prepare-distributed-hessian",
        "--job-dir",
        str(job_dir),
        "--output-dir",
        str(distributed),
    )
    plan_path = distributed / "distributed_hessian_plan.json"
    plan = json.loads(plan_path.read_text())
    assert plan["finite_difference"]["mode"] == "2_1"
    # A bent triatomic is Cs, so Psi4 reduces the C1-style 13-task plan to 11.
    assert plan["task_count"] == 11
    for task in plan["tasks"]:
        run(
            "run-distributed-hessian-task",
            "--plan",
            str(plan_path),
            "--task-id",
            task["id"],
            "--scratch-dir",
            str(tmp_path / "scratch" / task["id"]),
            "--threads",
            "1",
            "--memory-gib",
            "1",
        )
    assembled_path = distributed / "distributed_hessian_audit.json"
    run(
        "assemble-distributed-hessian",
        "--job-dir",
        str(job_dir),
        "--plan",
        str(plan_path),
        "--output",
        str(assembled_path),
    )
    assembled = json.loads(assembled_path.read_text())
    assert assembled["status"] == "assembled_unreviewed"
    assert assembled["task_count"] == 11
    assert assembled["frequency_count"] == 3
    assert assembled["imaginary_frequency_count"] == 0
    audit = audit_frequency_result(job_dir)
    assert audit["status"] == "passed_harmonic_minimum"
    assert audit["cartesian_hessian"]["status"] == "passed"

    # The transport/assembly path must reproduce the ordinary serial Psi4 driver,
    # not merely produce a plausible-looking positive Hessian.
    source = tmp_path / "water.xyz"
    parent = tmp_path / "optimized_model_audit.json"
    serial_job = tmp_path / "serial-frequency"
    generate_psi4_job(
        product_id="tt-cpd-cis-syn",
        model_id="distributed-hessian-water-test",
        xyz_path=source,
        output_dir=serial_job,
        job_kind="frequency",
        charge=0,
        multiplicity=1,
        atom_map=["1:O", "1:H1", "1:H2"],
        parent_manifest_path=parent,
        memory_gib=1,
        threads=1,
    )
    run(
        "run-qm-job",
        "--job-dir",
        str(serial_job),
        "--psi4",
        "/home/jojo/miniforge3/envs/nadoc-qm/bin/psi4",
        "--scratch-dir",
        str(tmp_path / "serial-scratch"),
    )
    serial_audit = audit_frequency_result(serial_job)
    assert serial_audit["status"] == "passed_harmonic_minimum"
    np.testing.assert_allclose(
        np.loadtxt(job_dir / "hessian_hartree_per_bohr2.txt"),
        np.loadtxt(serial_job / "hessian_hartree_per_bohr2.txt"),
        rtol=1e-7,
        atol=5e-8,
    )
