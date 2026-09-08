"""Safety checks for the optional, budget-capped distributed-Hessian offloader."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "runpod_photoproduct_hessian.py"
SPEC = importlib.util.spec_from_file_location("runpod_photoproduct_hessian", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan(tmp_path: Path) -> Path:
    task_dir = tmp_path / "tasks" / "0000-reference"
    task_dir.mkdir(parents=True)
    task_input = task_dir / "input.json"
    task_input.write_text("{}\n")
    plan_path = tmp_path / "distributed_hessian_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-distributed-hessian-plan.v1",
                "status": "prepared_not_run",
                "gate_effect": "none",
                "product_id": "tt-cpd-cis-syn-i",
                "model_id": "n1-methyl-tt-cpd-cis-syn-i",
                "task_count": 1,
                "engine": {
                    "version": "1.11",
                    "qcengine_version": "0.51.0",
                    "qcelemental_version": "0.51.0",
                },
                "frequency_job": {"path": str(tmp_path / "job_manifest.json")},
                "tasks": [
                    {
                        "id": "0000-reference",
                        "input": {
                            "path": "tasks/0000-reference/input.json",
                            "sha256": _sha256(task_input),
                        },
                        "result": {"path": "tasks/0000-reference/result.json"},
                        "run_record": {
                            "path": "tasks/0000-reference/run_record.json"
                        },
                    }
                ],
            }
        )
        + "\n"
    )
    return plan_path


def test_dry_run_writes_neutral_report_without_creating_pod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_path = _plan(tmp_path / "plan")
    output = tmp_path / "offload.json"
    monkeypatch.setattr(
        MODULE, "resolve_api_key", lambda: SimpleNamespace(value="test-key")
    )

    async def stock(_key: str) -> dict:
        return {
            "NVIDIA A40": {
                "stock": "High",
                "on_demand": 0.49,
            }
        }

    monkeypatch.setattr(MODULE, "fetch_gpu_stock", stock)

    class MustNotCreateClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("a dry run must not construct a billing client")

    monkeypatch.setattr(MODULE, "RunpodClient", MustNotCreateClient)
    args = argparse.Namespace(
        plan=plan_path,
        output=output,
        qm_python=Path(__import__("sys").executable),
        ssh_key=tmp_path / "ssh-key",
        network_volume_id="volume-test",
        gpu_type_id="NVIDIA A40",
        cloud_type="SECURE",
        budget_usd=2.0,
        campaign_ledger=None,
        campaign_cap_usd=10.0,
        maximum_seconds=4 * 3600,
        max_parallel=2,
        threads_per_task=4,
        memory_gib_per_task=6,
        execute=False,
    )
    args.ssh_key.write_text("test-only")
    report = asyncio.run(MODULE._run(args))
    assert report["status"] == "dry_run"
    assert report["gate_effect"] == "none"
    assert report["job_kind"] == "frequency"
    assert report["payload"]["terminateAfter"].endswith("Z")
    assert json.loads(output.read_text()) == report


def test_plan_input_tamper_fails_closed(tmp_path: Path) -> None:
    plan_path = _plan(tmp_path)
    (tmp_path / "tasks" / "0000-reference" / "input.json").write_text('{"changed":1}\n')
    with pytest.raises(ValueError, match="missing or changed"):
        MODULE._load_plan(plan_path)


def test_fixed_response_plan_is_distinct_and_supported(tmp_path: Path) -> None:
    plan_path = _plan(tmp_path)
    payload = json.loads(plan_path.read_text())
    payload["job_kind"] = "fixed_geometry_hessian"
    payload["fixed_geometry_hessian_job"] = payload.pop("frequency_job")
    plan_path.write_text(json.dumps(payload) + "\n")

    plan = MODULE._load_plan(plan_path)

    assert MODULE._plan_job_kind(plan) == "fixed_geometry_hessian"
    plan["frequency_job"] = {"path": "ambiguous"}
    with pytest.raises(ValueError, match="ambiguous QM job kind"):
        MODULE._plan_job_kind(plan)


def test_spend_authorization_requires_durable_storage_root(tmp_path: Path) -> None:
    plan_path = _plan(tmp_path / "plan")
    args = argparse.Namespace(
        plan=plan_path,
        output=tmp_path / "offload.json",
        execute=True,
        storage_root=None,
        campaign_ledger=None,
    )
    with pytest.raises(ValueError, match="requires --storage-root"):
        asyncio.run(MODULE._run(args))


def test_fixed_response_offload_selects_nonfrequency_local_audits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_path = _plan(tmp_path / "distributed")
    plan = json.loads(plan_path.read_text())
    job_dir = tmp_path / "fixed-job"
    job_dir.mkdir()
    job_manifest = job_dir / "job_manifest.json"
    job_manifest.write_text("{}\n")
    plan["job_kind"] = "fixed_geometry_hessian"
    plan["fixed_geometry_hessian_job"] = {"path": str(job_manifest)}
    plan.pop("frequency_job")
    plan_path.write_text(json.dumps(plan) + "\n")
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["cwd"] = kwargs["cwd"]
        (plan_path.parent / "distributed_fixed_hessian_audit.json").write_text(
            '{"status":"assembled_unreviewed_response"}\n'
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_audit(directory):
        assert directory == job_dir
        (job_dir / "fixed_geometry_hessian_audit.json").write_text(
            '{"status":"passed_candidate_response_evidence"}\n'
        )
        return {"status": "passed_candidate_response_evidence"}

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr(MODULE, "audit_fixed_geometry_hessian_result", fake_audit)

    result = MODULE._run_local_assembly(
        qm_python=Path("/fake/qm/python"),
        plan_path=plan_path,
        plan=plan,
    )

    assert "assemble-distributed-fixed-hessian" in observed["command"]
    assert observed["cwd"] == plan_path.parent
    assert result["job_kind"] == "fixed_geometry_hessian"
    assert result["fixed_geometry_hessian_audit"]["status"] == (
        "passed_candidate_response_evidence"
    )


def test_ephemeral_payload_is_not_pinned_to_volume() -> None:
    payload = MODULE.build_create_payload(
        name="ephemeral-qm",
        gpu_type_ids=["NVIDIA A40"],
        network_volume_id=None,
    )
    assert "networkVolumeId" not in payload
    assert "volumeMountPath" not in payload


def test_cgroup_quota_overrides_misleading_nproc() -> None:
    limits = MODULE._parse_cgroup_limits("128\n1360000 100000\n878718009344\n")
    assert limits["advertised_logical_cpus"] == 128
    assert limits["cgroup_cpu_limit"] == pytest.approx(13.6)
    assert limits["cgroup_memory_limit_bytes"] == 878718009344
    unlimited = MODULE._parse_cgroup_limits("8\nmax\nmax\n")
    assert unlimited["cgroup_cpu_limit"] == 8
    assert unlimited["cgroup_memory_limit_bytes"] is None
    probe = MODULE._cgroup_probe_command()
    assert "/sys/fs/cgroup/cpu.max" in probe
    assert "/sys/fs/cgroup/cpu/cpu.cfs_quota_us" in probe


def test_plan_archive_carries_only_complete_audited_resume_pairs(tmp_path: Path) -> None:
    plan_path = _plan(tmp_path / "plan")
    plan = MODULE._load_plan(plan_path)
    task_dir = plan_path.parent / "tasks" / "0000-reference"
    result = task_dir / "result.json"
    result.write_text('{"success":true}\n')
    run_record = task_dir / "run_record.json"
    run_record.write_text(
        json.dumps(
            {
                "status": "completed_unreviewed",
                "plan_sha256": _sha256(plan_path),
                "task_id": "0000-reference",
                "result": {"sha256": _sha256(result)},
            }
        )
        + "\n"
    )
    archive_path = tmp_path / "plan.tar.gz"
    MODULE._plan_archive(plan_path, archive_path, plan)
    with tarfile.open(archive_path, "r:gz") as archive:
        names = set(archive.getnames())
    assert "distributed/tasks/0000-reference/result.json" in names
    assert "distributed/tasks/0000-reference/run_record.json" in names
