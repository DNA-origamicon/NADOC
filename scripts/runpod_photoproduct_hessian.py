#!/usr/bin/env python3
"""Run one prepared photoproduct Hessian task set on a budget-capped RunPod Pod.

The GPU is incidental for this CPU workload; RunPod Pods couple vCPUs to a GPU.  This
driver exists to add CPU workers while the local workstation is busy.  It stages only
immutable QCSchema inputs and NADOC source, installs the pinned open-source QM stack on
the persistent volume, runs tasks independently, downloads hash-audited results, then
assembles and audits the frequency or reviewed fixed-geometry response locally. The Pod
is destroyed on every ordinary exit.
An independent user-systemd watchdog destroys the exact pod when this controller dies or
the local deadline is reached; provider ``terminateAfter`` is retained only as an
additional hint because it has failed in observed production use.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.runpod_api import (  # noqa: E402
    RunpodClient,
    build_create_payload,
    resolve_api_key,
    ssh_endpoint,
    termination_deadline,
)
from backend.core.runpod_conn import RunpodConnection  # noqa: E402
from backend.core.runpod_preflight import fetch_gpu_stock  # noqa: E402
from backend.core.runpod_oxdna import CampaignLedger  # noqa: E402
from backend.core.runpod_watchdog import start_watchdog_service  # noqa: E402
from backend.core.photoproduct_storage import (  # noqa: E402
    validate_photoproduct_storage_root,
)
from backend.parameterization.photoproduct_qm import (  # noqa: E402
    audit_frequency_result,
)
from backend.parameterization.photoproduct_coupled_conformer import (  # noqa: E402
    audit_fixed_geometry_hessian_result,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_cgroup_limits(stdout: str) -> dict[str, Any]:
    """Parse the enforceable Pod limits; advertised ``nproc`` alone is misleading."""

    lines = stdout.splitlines()
    if len(lines) != 3:
        raise ValueError("could not read remote CPU/memory cgroup limits")
    logical_cpus = int(lines[0])
    quota_fields = lines[1].split()
    if quota_fields == ["max"]:
        cpu_limit = float(logical_cpus)
    elif len(quota_fields) == 2:
        cpu_limit = int(quota_fields[0]) / int(quota_fields[1])
    else:
        raise ValueError("malformed remote cpu.max")
    memory_limit = None if lines[2] == "max" else int(lines[2])
    if logical_cpus < 1 or cpu_limit <= 0 or (memory_limit is not None and memory_limit <= 0):
        raise ValueError("invalid remote cgroup resource limits")
    return {
        "advertised_logical_cpus": logical_cpus,
        "cgroup_cpu_limit": cpu_limit,
        "cgroup_memory_limit_bytes": memory_limit,
    }


def _cgroup_probe_command() -> str:
    """Read cgroup-v2 or legacy-v1 limits without letting a missing memory file fail."""

    return "\n".join(
        [
            "set -euo pipefail",
            "nproc",
            "if [ -r /sys/fs/cgroup/cpu.max ]; then",
            "  cat /sys/fs/cgroup/cpu.max",
            "elif [ -r /sys/fs/cgroup/cpu/cpu.cfs_quota_us ]; then",
            "  q=$(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us)",
            "  p=$(cat /sys/fs/cgroup/cpu/cpu.cfs_period_us)",
            "  if [ \"$q\" -lt 0 ]; then echo max; else echo \"$q $p\"; fi",
            "elif [ -r /sys/fs/cgroup/cpu,cpuacct/cpu.cfs_quota_us ]; then",
            "  q=$(cat /sys/fs/cgroup/cpu,cpuacct/cpu.cfs_quota_us)",
            "  p=$(cat /sys/fs/cgroup/cpu,cpuacct/cpu.cfs_period_us)",
            "  if [ \"$q\" -lt 0 ]; then echo max; else echo \"$q $p\"; fi",
            "else",
            "  echo unknown",
            "fi",
            "if [ -r /sys/fs/cgroup/memory.max ]; then",
            "  cat /sys/fs/cgroup/memory.max",
            "elif [ -r /sys/fs/cgroup/memory/memory.limit_in_bytes ]; then",
            "  cat /sys/fs/cgroup/memory/memory.limit_in_bytes",
            "else",
            "  echo max",
            "fi",
        ]
    )


def _load_plan(path: Path) -> dict[str, Any]:
    plan = json.loads(path.read_text())
    if (
        plan.get("schema") != "nadoc.photoproduct-distributed-hessian-plan.v1"
        or plan.get("status") != "prepared_not_run"
        or plan.get("gate_effect") != "none"
        or not isinstance(plan.get("tasks"), list)
        or len(plan["tasks"]) != plan.get("task_count")
    ):
        raise ValueError("a neutral distributed-Hessian plan is required")
    root = path.parent.resolve()
    for task in plan["tasks"]:
        task_path = (root / task["input"]["path"]).resolve()
        task_path.relative_to(root)
        if not task_path.is_file() or _sha256(task_path) != task["input"]["sha256"]:
            raise ValueError(f"task input is missing or changed: {task.get('id')}")
    required = {
        "version": "1.11",
        "qcengine_version": "0.51.0",
        "qcelemental_version": "0.51.0",
    }
    if any(plan.get("engine", {}).get(key) != value for key, value in required.items()):
        raise ValueError("plan does not use the supported pinned distributed-QM stack")
    _plan_job_kind(plan)
    return plan


def _plan_job_kind(plan: dict[str, Any]) -> str:
    """Identify old frequency plans and versioned fixed-response plans unambiguously."""

    declared = plan.get("job_kind")
    has_frequency = isinstance(plan.get("frequency_job"), dict)
    has_fixed = isinstance(plan.get("fixed_geometry_hessian_job"), dict)
    if declared in {None, "frequency"} and has_frequency and not has_fixed:
        return "frequency"
    if declared == "fixed_geometry_hessian" and has_fixed and not has_frequency:
        return "fixed_geometry_hessian"
    raise ValueError("distributed plan has an absent or ambiguous QM job kind")


def _source_archive(path: Path) -> None:
    include = [
        ROOT / "backend" / "__init__.py",
        ROOT / "backend" / "core" / "__init__.py",
        ROOT / "backend" / "core" / "photoproduct_chemistry.py",
        ROOT / "backend" / "core" / "photoproduct_registry.py",
        ROOT / "backend" / "parameterization" / "__init__.py",
        ROOT / "backend" / "parameterization" / "photoproduct_qm.py",
        ROOT / "backend" / "parameterization" / "photoproduct_distributed_hessian.py",
    ]
    include.extend(
        sorted((ROOT / "backend" / "data" / "forcefield").glob("photoproduct_qm_protocol*.json"))
    )
    include.extend(
        [
            ROOT / "backend" / "data" / "forcefield" / "photoproduct_registry.json",
            *sorted(
                (ROOT / "backend" / "data" / "forcefield" / "photoproducts").rglob("*.json")
            ),
        ]
    )
    missing = [item for item in include if not item.is_file()]
    if missing:
        raise FileNotFoundError(f"remote source bundle is missing: {missing[0]}")
    with tarfile.open(path, "w:gz") as archive:
        for item in include:
            archive.add(item, arcname=item.relative_to(ROOT))


def _plan_archive(plan_path: Path, path: Path, plan: dict[str, Any]) -> None:
    root = plan_path.parent.resolve()
    resumable: set[Path] = set()
    for task in plan["tasks"]:
        result = (root / task["result"]["path"]).resolve()
        run_record = (root / task["run_record"]["path"]).resolve()
        result.relative_to(root)
        run_record.relative_to(root)
        if result.is_file() and run_record.is_file():
            record = json.loads(run_record.read_text())
            if (
                record.get("status") != "completed_unreviewed"
                or (record.get("result") or {}).get("sha256") != _sha256(result)
                or record.get("plan_sha256") != _sha256(plan_path)
                or record.get("task_id") != task["id"]
            ):
                raise ValueError(f"local resume evidence failed audit: {task['id']}")
            resumable.update({result, run_record})
    with tarfile.open(path, "w:gz") as archive:
        for item in sorted(root.rglob("*")):
            if item.is_file() and (
                item.name in {"distributed_hessian_plan.json", "input.json"}
                or item.resolve() in resumable
            ):
                archive.add(item, arcname=Path("distributed") / item.relative_to(root))


def _extract_results(
    archive_path: Path,
    *,
    plan_path: Path,
    plan: dict[str, Any],
    require_complete: bool = True,
) -> None:
    root = plan_path.parent.resolve()
    allowed = {
        str(Path(task[record]["path"]))
        for task in plan["tasks"]
        for record in ("result", "run_record")
    }
    allowed.update({"compute_environment.json", "micromamba.sha256"})
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        unexpected = names - allowed
        if unexpected or any(not member.isfile() for member in members):
            raise ValueError(
                "remote result archive contains an unexpected or non-regular member: "
                + ", ".join(sorted(unexpected)[:3])
            )
        required = {
            str(Path(task[record]["path"]))
            for task in plan["tasks"]
            for record in ("result", "run_record")
        }
        if require_complete and not required.issubset(names):
            raise ValueError("remote result archive is missing one or more task results")
        for member in members:
            target = (root / member.name).resolve()
            target.relative_to(root)
            payload = archive.extractfile(member)
            if payload is None:
                raise ValueError(f"failed to read remote result member: {member.name}")
            data = payload.read()
            if target.exists():
                if target.read_bytes() != data:
                    raise FileExistsError(f"remote result conflicts with local evidence: {target}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def _run_local_assembly(
    *, qm_python: Path, plan_path: Path, plan: dict[str, Any]
) -> dict[str, Any]:
    job_kind = _plan_job_kind(plan)
    job_record_key = (
        "frequency_job"
        if job_kind == "frequency"
        else "fixed_geometry_hessian_job"
    )
    job_path = Path(plan[job_record_key]["path"])
    job_dir = job_path.parent
    if job_kind == "frequency":
        command = "assemble-distributed-hessian"
        output_path = plan_path.parent / "distributed_hessian_audit.json"
    else:
        command = "assemble-distributed-fixed-hessian"
        output_path = plan_path.parent / "distributed_fixed_hessian_audit.json"
    completed = subprocess.run(
        [
            str(qm_python),
            str(ROOT / "scripts" / "photoproduct_workflow.py"),
            command,
            "--job-dir",
            str(job_dir),
            "--plan",
            str(plan_path),
            "--output",
            str(output_path),
        ],
        # Psi4 may write timer.dat during plan recreation. Keep all assembly
        # housekeeping beside the Archive-backed plan rather than in the checkout.
        cwd=plan_path.parent,
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    if completed.returncode:
        raise RuntimeError(
            "local distributed-Hessian assembly failed: "
            + (completed.stdout + completed.stderr)[-2000:]
        )
    if job_kind == "frequency":
        downstream = audit_frequency_result(job_dir)
        downstream_name = "frequency_audit"
        downstream_path = job_dir / "frequency_audit.json"
    else:
        downstream = audit_fixed_geometry_hessian_result(job_dir)
        downstream_name = "fixed_geometry_hessian_audit"
        downstream_path = job_dir / "fixed_geometry_hessian_audit.json"
    assembly_record = {
        "path": str(output_path.resolve()),
        "sha256": _sha256(output_path),
    }
    result = {
        "job_kind": job_kind,
        "distributed_assembly_audit": assembly_record,
        downstream_name: {
            "path": str(downstream_path.resolve()),
            "sha256": _sha256(downstream_path),
            "status": downstream["status"],
        },
    }
    # Retain the original frequency-report key for existing campaign consumers.
    result[
        "distributed_hessian_audit"
        if job_kind == "frequency"
        else "distributed_fixed_hessian_audit"
    ] = assembly_record
    return result


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    plan_path = args.plan.resolve()
    plan = _load_plan(plan_path)
    job_kind = _plan_job_kind(plan)
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite RunPod offload report: {args.output}")
    storage_root = getattr(args, "storage_root", None)
    storage = None
    if storage_root is not None:
        storage_status = validate_photoproduct_storage_root(storage_root)
        root = Path(storage_status["storage_root"])
        checked = {"plan": plan_path, "output": args.output.resolve()}
        if args.campaign_ledger is not None:
            checked["campaign_ledger"] = args.campaign_ledger.resolve()
        for label, path in checked.items():
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"{label} must be under RunPod storage root {root}") from exc
        storage = {
            **storage_status,
            "root": str(root),
            **{key: str(value) for key, value in checked.items()},
        }
    elif args.execute:
        raise ValueError("--execute requires --storage-root for durable local staging")
    if not args.qm_python.is_file():
        raise FileNotFoundError(f"local pinned QM Python is missing: {args.qm_python}")
    if not args.ssh_key.is_file():
        raise FileNotFoundError(
            f"RunPod SSH private key is missing: {args.ssh_key}; create/register it "
            "before renting a Pod"
        )
    resolved = resolve_api_key()
    if not resolved.value:
        raise RuntimeError("RunPod API key is unavailable ($RUNPOD_API_KEY or ~/.runpod_key)")
    stock = await fetch_gpu_stock(resolved.value)
    quote = stock.get(args.gpu_type_id) or {}
    rate = quote.get("on_demand")
    if not isinstance(rate, (int, float)) or rate <= 0:
        raise RuntimeError(f"RunPod has no live on-demand quote for {args.gpu_type_id}")
    if quote.get("stock") not in {"High", "Medium", "Low"}:
        raise RuntimeError(f"RunPod reports no stock for {args.gpu_type_id}")
    ledger = (
        CampaignLedger(args.campaign_ledger, cap_usd=args.campaign_cap_usd)
        if args.campaign_ledger is not None
        else None
    )
    open_campaign_pods = ledger.open_pod_ids() if ledger is not None else []
    if args.execute and open_campaign_pods:
        raise RuntimeError(
            "campaign ledger already has an open billing Pod; refusing concurrent "
            "authorization: " + ", ".join(open_campaign_pods)
        )
    remaining_campaign_usd = ledger.remaining_usd() if ledger is not None else None
    lifetime_seconds = min(
        int(args.budget_usd / rate * 3600),
        args.maximum_seconds,
        (
            int(remaining_campaign_usd / rate * 3600)
            if remaining_campaign_usd is not None
            else args.maximum_seconds
        ),
    )
    if lifetime_seconds < 900:
        raise ValueError("budget buys less than the 15-minute safe setup minimum")
    payload = build_create_payload(
        name=f"nadoc-fd-{plan['product_id']}",
        gpu_type_ids=[args.gpu_type_id],
        network_volume_id=args.network_volume_id,
        cloud_type=args.cloud_type,
        interruptible=False,
        terminate_after=termination_deadline(lifetime_seconds),
    )
    if not args.execute:
        report = {
            "schema": "nadoc.photoproduct-runpod-hessian-offload.v1",
            "status": "dry_run",
            "gate_effect": "none",
            "product_id": plan["product_id"],
            "model_id": plan["model_id"],
            "job_kind": job_kind,
            "plan": {"path": str(plan_path), "sha256": _sha256(plan_path)},
            "task_count": plan["task_count"],
            "quote": {
                "gpu_type_id": args.gpu_type_id,
                "cloud_type": args.cloud_type,
                "stock": quote["stock"],
                "usd_per_hour": rate,
            },
            "budget_usd": args.budget_usd,
            "campaign": {
                "ledger": (
                    str(args.campaign_ledger.resolve())
                    if args.campaign_ledger is not None
                    else None
                ),
                "cap_usd": args.campaign_cap_usd,
                "remaining_before_usd": remaining_campaign_usd,
                "open_pod_ids": open_campaign_pods,
            },
            "maximum_lifetime_seconds": lifetime_seconds,
            "payload": {key: value for key, value in payload.items() if key != "env"},
            "execution_note": "No Pod was created; pass --execute to authorize spend.",
            "storage_confinement": storage,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        return report
    client = RunpodClient(
        resolved.value,
        audit_dir=args.output.parent,
    )
    pod_record: dict[str, Any] = {}
    started = time.monotonic()
    started_at = _utc_now()
    results: dict[str, Any] | None = None
    failure: str | None = None
    remote_limits: dict[str, Any] | None = None
    provider_absent_at_controller_exit: bool | None = None
    try:
        def created(info) -> None:
            actual_rate = float(info.cost_per_hr or rate)
            if ledger is not None:
                ledger.authorize(actual_rate, lifetime_seconds)
                ledger.open_pod(
                    info.id,
                    actual_rate,
                    note=f"photoproduct Hessian {plan['product_id']}",
                )
            pod_record.update(
                {
                    "id": info.id,
                    "reported_usd_per_hour": info.cost_per_hr,
                    "desired_status_at_creation": info.desired_status,
                }
            )
            watchdog_unit = start_watchdog_service(
                pod_id=info.id,
                owner_pid=os.getpid(),
                deadline=payload["terminateAfter"],
                audit_dir=args.output.parent,
                campaign_ledger=args.campaign_ledger,
                campaign_cap_usd=args.campaign_cap_usd,
                poll_seconds=args.watchdog_poll_seconds,
            )
            pod_record["independent_watchdog_unit"] = watchdog_unit
            client.record_lifecycle(
                "independent_watchdog_service_started",
                pod_id=info.id,
                unit=watchdog_unit,
                controller_pid=os.getpid(),
            )

        staging_parent = storage_root.resolve() / "runpod_staging"
        staging_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="nadoc-runpod-fd-", dir=staging_parent
        ) as temporary:
            temporary_path = Path(temporary)
            source_archive = temporary_path / "source.tar.gz"
            plan_archive = temporary_path / "plan.tar.gz"
            result_archive = temporary_path / "results.tar.gz"
            _source_archive(source_archive)
            _plan_archive(plan_path, plan_archive, plan)
            async with client.pod(
                payload,
                on_created=created,
                wait_timeout_s=600,
                terminate_on_exit=True,
            ) as pod:
                endpoint = ssh_endpoint(pod)
                if endpoint is None:
                    raise RuntimeError("ready RunPod Pod has no SSH endpoint")
                connection = RunpodConnection(
                    host=endpoint[0],
                    port=endpoint[1],
                    pod_id=pod.id,
                    client_keys=[str(args.ssh_key.resolve())],
                )
                await connection.connect()
                try:
                    limit_result = await connection.run(
                        _cgroup_probe_command(),
                        timeout=30,
                    )
                    if limit_result.rc:
                        raise RuntimeError("could not inspect the Pod's cgroup limits")
                    remote_limits = _parse_cgroup_limits(limit_result.stdout)
                    requested_cpus = args.max_parallel * args.threads_per_task
                    if requested_cpus > math.ceil(remote_limits["cgroup_cpu_limit"]):
                        raise RuntimeError(
                            f"requested {requested_cpus} concurrent CPU threads but the "
                            f"Pod cgroup permits {remote_limits['cgroup_cpu_limit']:g}"
                        )
                    requested_memory = (
                        args.max_parallel * args.memory_gib_per_task * 1024**3
                    )
                    memory_limit = remote_limits["cgroup_memory_limit_bytes"]
                    if memory_limit is not None and requested_memory > memory_limit:
                        raise RuntimeError(
                            "requested concurrent task memory exceeds the Pod cgroup limit"
                        )
                    run_id = _sha256(plan_path)[:16]
                    remote_root = f"/workspace/nadoc_photoproduct_hessian/runs/{run_id}"
                    tool_root = "/workspace/nadoc_photoproduct_hessian/toolchain"
                    remote_source = f"{remote_root}/source.tar.gz"
                    remote_plan = f"{remote_root}/plan.tar.gz"
                    await connection.mkdir_p(remote_root)
                    await connection.sftp_put(str(source_archive), remote_source)
                    await connection.sftp_put(str(plan_archive), remote_plan)
                    setup = "\n".join(
                        [
                            "set -euo pipefail",
                            f"mkdir -p {shlex.quote(tool_root)} {shlex.quote(remote_root + '/code')}",
                            f"if [ ! -x {shlex.quote(tool_root + '/bin/micromamba')} ]; then",
                            f"  curl -LsSf https://micro.mamba.pm/api/micromamba/linux-64/2.3.3 | tar -xj -C {shlex.quote(tool_root)} bin/micromamba",
                            "fi",
                            f"sha256sum {shlex.quote(tool_root + '/bin/micromamba')} > {shlex.quote(remote_root + '/micromamba.sha256')}",
                            f"tar -xzf {shlex.quote(remote_source)} -C {shlex.quote(remote_root + '/code')}",
                            f"tar -xzf {shlex.quote(remote_plan)} -C {shlex.quote(remote_root)}",
                            f"if [ ! -x {shlex.quote(tool_root + '/qm-1.11/bin/python')} ]; then",
                            f"  MAMBA_ROOT_PREFIX={shlex.quote(tool_root + '/mamba-root')} {shlex.quote(tool_root + '/bin/micromamba')} create -y -p {shlex.quote(tool_root + '/qm-1.11')} -c conda-forge python=3.12 psi4=1.11 qcengine=0.51.0 qcelemental=0.51.0 numpy=2.5.2",
                            "fi",
                            f"{shlex.quote(tool_root + '/qm-1.11/bin/python')} -c \"import psi4,qcengine,qcelemental,numpy; assert (psi4.__version__,qcengine.__version__,qcelemental.__version__,numpy.__version__)==('1.11','0.51.0','0.51.0','2.5.2')\"",
                        ]
                    )
                    setup_result = await connection.run(setup, timeout=1800)
                    if setup_result.rc:
                        raise RuntimeError(
                            "remote QM environment setup failed: "
                            + (setup_result.stdout + setup_result.stderr)[-2000:]
                        )
                    remote_plan_path = f"{remote_root}/distributed/distributed_hessian_plan.json"
                    remote_tasks = f"{remote_root}/distributed/tasks"
                    batch = "\n".join(
                        [
                            "set -euo pipefail",
                            f"export PYTHONPATH={shlex.quote(remote_root + '/code')}",
                            f"export RUNPOD_POD_ID={shlex.quote(pod.id)}",
                            f"find {shlex.quote(remote_tasks)} -mindepth 1 -maxdepth 1 -type d -printf '%f\\n' | sort | xargs -r -n 1 -P {int(args.max_parallel)} bash -c '",
                            "  id=\"$1\"",
                            f"  task={shlex.quote(remote_tasks)}/\"$id\"",
                            "  if [ -s \"$task/result.json\" ] && [ -s \"$task/run_record.json\" ]; then exit 0; fi",
                            "  if [ -e \"$task/result.json\" ] || [ -e \"$task/run_record.json\" ]; then exit 91; fi",
                            f"  {shlex.quote(tool_root + '/qm-1.11/bin/python')} -m backend.parameterization.photoproduct_distributed_hessian run-task --plan {shlex.quote(remote_plan_path)} --task-id \"$id\" --scratch-dir {shlex.quote(remote_root + '/scratch')}/\"$id\" --threads {int(args.threads_per_task)} --memory-gib {int(args.memory_gib_per_task)} > \"$task/worker.stdout\" 2> \"$task/worker.stderr\"",
                            "' _",
                        ]
                    )
                    batch_task = asyncio.create_task(
                        connection.run(batch, timeout=float(lifetime_seconds))
                    )
                    while True:
                        done, _pending = await asyncio.wait(
                            {batch_task}, timeout=float(args.checkpoint_seconds)
                        )
                        if done:
                            batch_result = batch_task.result()
                            break
                        checkpoint_command = "\n".join(
                            [
                                "set -euo pipefail",
                                f"cd {shlex.quote(remote_root + '/distributed')}",
                                "find tasks -type f \\( -name result.json -o -name run_record.json \\) -print > checkpoint-files.txt",
                                "tar -czf checkpoint.tar.gz -T checkpoint-files.txt",
                            ]
                        )
                        checkpoint_result = await connection.run(
                            checkpoint_command, timeout=120
                        )
                        if checkpoint_result.rc:
                            raise RuntimeError("remote checkpoint packaging failed")
                        checkpoint_archive = temporary_path / "checkpoint.tar.gz"
                        await connection.sftp_get(
                            f"{remote_root}/distributed/checkpoint.tar.gz",
                            str(checkpoint_archive),
                        )
                        _extract_results(
                            checkpoint_archive,
                            plan_path=plan_path,
                            plan=plan,
                            require_complete=False,
                        )
                    if batch_result.rc:
                        raise RuntimeError(
                            "remote displaced-gradient batch failed: "
                            + (batch_result.stdout + batch_result.stderr)[-2000:]
                        )
                    environment_path = f"{remote_root}/distributed/compute_environment.json"
                    environment_command = "\n".join(
                        [
                            "set -euo pipefail",
                            f"{shlex.quote(tool_root + '/qm-1.11/bin/python')} - <<'PY' > {shlex.quote(environment_path)}",
                            "import json, os, platform, psi4, qcengine, qcelemental, numpy",
                            "print(json.dumps({'psi4':psi4.__version__,'qcengine':qcengine.__version__,'qcelemental':qcelemental.__version__,'numpy':numpy.__version__,'platform':platform.platform(),'machine':platform.machine(),'logical_cpu_count':os.cpu_count()}, indent=2))",
                            "PY",
                            f"cp {shlex.quote(remote_root + '/micromamba.sha256')} {shlex.quote(remote_root + '/distributed/micromamba.sha256')}",
                            f"cd {shlex.quote(remote_root + '/distributed')}",
                            "find tasks -type f \\( -name result.json -o -name run_record.json \\) -print > result-files.txt",
                            "printf '%s\\n' compute_environment.json micromamba.sha256 >> result-files.txt",
                            "tar -czf results.tar.gz -T result-files.txt",
                        ]
                    )
                    environment_result = await connection.run(
                        environment_command, timeout=300
                    )
                    if environment_result.rc:
                        raise RuntimeError(
                            "remote result packaging failed: "
                            + (environment_result.stdout + environment_result.stderr)[-2000:]
                        )
                    await connection.sftp_get(
                        f"{remote_root}/distributed/results.tar.gz",
                        str(result_archive),
                    )
                finally:
                    await connection.close()
            _extract_results(result_archive, plan_path=plan_path, plan=plan)
            results = _run_local_assembly(
                qm_python=args.qm_python,
                plan_path=plan_path,
                plan=plan,
            )
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        elapsed = time.monotonic() - started
        if pod_record.get("id"):
            try:
                provider_pods = await client.list_pods()
                provider_absent_at_controller_exit = not any(
                    pod.id == pod_record["id"] for pod in provider_pods
                )
            except Exception as exc:
                client.record_lifecycle(
                    "controller_exit_provider_check_failed",
                    pod_id=pod_record["id"],
                    error=f"{type(exc).__name__}: {exc}",
                )
            if provider_absent_at_controller_exit:
                if ledger is not None:
                    ledger.close_pod(pod_record["id"])
            else:
                client.record_lifecycle(
                    "controller_exit_ledger_left_open_for_watchdog",
                    pod_id=pod_record["id"],
                )
        report = {
            "schema": "nadoc.photoproduct-runpod-hessian-offload.v1",
            "status": "passed" if results is not None and failure is None else "failed",
            "gate_effect": "none",
            "product_id": plan["product_id"],
            "model_id": plan["model_id"],
            "job_kind": job_kind,
            "plan": {"path": str(plan_path), "sha256": _sha256(plan_path)},
            "started_at": started_at,
            "finished_at": _utc_now(),
            "elapsed_seconds": elapsed,
            "budget_usd": args.budget_usd,
            "quoted_usd_per_hour": rate,
            "estimated_compute_cost_usd": elapsed * rate / 3600.0,
            "maximum_lifetime_seconds": lifetime_seconds,
            "pod": pod_record,
            "resources": {
                "max_parallel": args.max_parallel,
                "threads_per_task": args.threads_per_task,
                "memory_gib_per_task": args.memory_gib_per_task,
                "remote_limits": remote_limits,
            },
            "results": results,
            "storage_confinement": storage,
            "error": failure,
            "termination_policy": (
                "client context destroys the Pod on exit; an exact-pod user-systemd "
                "watchdog terminates on controller loss or local deadline; provider "
                "terminateAfter is advisory defense in depth"
            ),
            "provider_absent_at_controller_exit": provider_absent_at_controller_exit,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if not args.output.exists():
            args.output.write_text(json.dumps(report, indent=2) + "\n")
        await client.aclose()
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=(
            Path(os.environ["NADOC_PHOTOPRODUCT_STORAGE_ROOT"])
            if os.environ.get("NADOC_PHOTOPRODUCT_STORAGE_ROOT")
            else None
        ),
        help=(
            "Confine local plan, report, spend ledger, and temporary transfer staging "
            "to this durable root; required with --execute."
        ),
    )
    parser.add_argument(
        "--qm-python",
        type=Path,
        default=Path("/home/jojo/miniforge3/envs/nadoc-qm/bin/python"),
    )
    parser.add_argument(
        "--ssh-key",
        type=Path,
        default=Path.home() / ".ssh" / "id_ed25519",
        help="Private key matching a public key registered in RunPod account settings.",
    )
    parser.add_argument(
        "--network-volume-id",
        help=(
            "Optional persistent volume for environment caching. Omit it to let RunPod "
            "place this self-contained job in any compatible datacenter."
        ),
    )
    parser.add_argument("--gpu-type-id", default="NVIDIA A40")
    parser.add_argument(
        "--cloud-type",
        choices=("SECURE",),
        default="SECURE",
        help="Pinned to Secure Cloud so the live quote and rented market are identical.",
    )
    parser.add_argument("--budget-usd", type=float, default=2.0)
    parser.add_argument(
        "--campaign-ledger",
        type=Path,
        help="Required with --execute; durable ledger shared by every campaign attempt.",
    )
    parser.add_argument("--campaign-cap-usd", type=float, default=10.0)
    parser.add_argument("--maximum-seconds", type=int, default=4 * 3600)
    parser.add_argument("--max-parallel", type=int, default=2)
    parser.add_argument("--threads-per-task", type=int, default=4)
    parser.add_argument("--memory-gib-per-task", type=int, default=6)
    parser.add_argument(
        "--checkpoint-seconds",
        type=int,
        default=300,
        help="Download completed immutable task pairs at this interval.",
    )
    parser.add_argument(
        "--watchdog-poll-seconds",
        type=float,
        default=30.0,
        help="Independent user-systemd exact-pod watchdog polling interval.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually rent a Pod; without this flag the command is a read-only dry run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.budget_usd <= 0 or args.maximum_seconds <= 0 or args.campaign_cap_usd <= 0:
        raise ValueError("budget and maximum duration must be positive")
    if args.budget_usd > 10 or args.campaign_cap_usd > 10:
        raise ValueError("this goal authorizes at most $10 of RunPod compute")
    if args.execute and args.campaign_ledger is None:
        raise ValueError("--execute requires --campaign-ledger for cumulative spend control")
    if min(
        args.max_parallel,
        args.threads_per_task,
        args.memory_gib_per_task,
        args.checkpoint_seconds,
        args.watchdog_poll_seconds,
    ) < 1:
        raise ValueError("parallelism, threads, memory, and checkpoint interval must be positive")
    report = asyncio.run(_run(args))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
