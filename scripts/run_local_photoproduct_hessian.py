#!/usr/bin/env python3
"""Run and audit a prepared photoproduct Hessian as a resumable local batch."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.parameterization.photoproduct_distributed_hessian import (  # noqa: E402
    assemble_distributed_hessian,
)
from backend.parameterization.photoproduct_qm import (  # noqa: E402
    audit_frequency_result,
)
from backend.core.photoproduct_storage import (  # noqa: E402
    validate_photoproduct_storage_root,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_passed_predecessor(report_path: Path) -> dict[str, Any]:
    if not report_path.is_file():
        raise ValueError(f"predecessor report is missing: {report_path}")
    report = json.loads(report_path.read_text())
    frequency = report.get("frequency_audit") or {}
    assembly = report.get("assembly") or {}
    if (
        report.get("schema") != "nadoc.photoproduct-local-hessian-batch.v1"
        or report.get("status") != "passed"
        or report.get("error") is not None
        or not isinstance(assembly.get("sha256"), str)
        or len(assembly["sha256"]) != 64
        or frequency.get("status")
        not in {"passed_harmonic_minimum", "passed_candidate_harmonic_minimum"}
        or not isinstance(frequency.get("sha256"), str)
        or len(frequency["sha256"]) != 64
    ):
        raise ValueError("predecessor Hessian report is not a passed assembly/minimum")
    return {
        "path": str(report_path.resolve()),
        "sha256": _sha256(report_path),
        "product_id": report.get("product_id"),
        "status": report["status"],
        "frequency_status": frequency["status"],
    }


def _wait_for_passed_predecessor(
    *, report_path: Path, service: str, poll_seconds: float
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.@:-]+", service):
        raise ValueError("predecessor service name contains unsupported characters")
    if not math.isfinite(poll_seconds) or poll_seconds <= 0:
        raise ValueError("predecessor poll interval must be positive")
    print(
        f"waiting for predecessor {service} and passed report {report_path}",
        flush=True,
    )
    polls = 0
    while True:
        active = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", service],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
        if not active:
            break
        time.sleep(poll_seconds)
        polls += 1
        if polls % 20 == 0:
            print(f"still waiting for predecessor {service}", flush=True)
    return _validate_passed_predecessor(report_path)


def _validate_storage_root(
    storage_root: Path, *, paths: dict[str, Path]
) -> dict[str, str]:
    """Fail before waiting or running when a durable path escapes the selected store."""

    storage = validate_photoproduct_storage_root(storage_root)
    root = Path(storage["storage_root"])
    resolved = {}
    for label, path in paths.items():
        candidate = path.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"{label} must be located under storage root {root}") from exc
        resolved[label] = str(candidate)
    return {**storage, "root": str(root), **resolved}


def _load_plan(plan_path: Path) -> tuple[dict[str, Any], Path]:
    plan = json.loads(plan_path.read_text())
    root = plan_path.parent.resolve()
    if (
        plan.get("schema") != "nadoc.photoproduct-distributed-hessian-plan.v1"
        or plan.get("status") != "prepared_not_run"
        or plan.get("gate_effect") != "none"
        or not isinstance(plan.get("tasks"), list)
        or len(plan["tasks"]) != plan.get("task_count")
    ):
        raise ValueError("unsupported or malformed distributed Hessian plan")
    for task in plan["tasks"]:
        input_path = (root / task["input"]["path"]).resolve()
        input_path.relative_to(root)
        if not input_path.is_file() or _sha256(input_path) != task["input"]["sha256"]:
            raise ValueError(f"distributed task input is missing or changed: {task.get('id')}")
    return plan, root


def _completion_state(
    *, plan_path: Path, root: Path, task: dict[str, Any]
) -> str:
    result_path = (root / task["result"]["path"]).resolve()
    run_path = (root / task["run_record"]["path"]).resolve()
    result_path.relative_to(root)
    run_path.relative_to(root)
    if result_path.exists() != run_path.exists():
        raise ValueError(f"task has an incomplete result/run-record pair: {task['id']}")
    if not result_path.exists():
        return "pending"
    run = json.loads(run_path.read_text())
    if (
        run.get("schema") != "nadoc.photoproduct-distributed-hessian-task-run.v1"
        or run.get("status") != "completed_unreviewed"
        or run.get("gate_effect") != "none"
        or run.get("plan_sha256") != _sha256(plan_path)
        or run.get("task_id") != task["id"]
        or run.get("input_sha256") != task["input"]["sha256"]
        or (run.get("result") or {}).get("sha256") != _sha256(result_path)
    ):
        raise ValueError(f"existing task result is not safely resumable: {task['id']}")
    return "complete"


def _validate_frequency_job_copy(
    *, plan: dict[str, Any], job_dir: Path
) -> dict[str, Any]:
    """Accept a relocated job directory only when its immutable bytes still match."""

    record = plan.get("frequency_job")
    if not isinstance(record, dict):
        raise ValueError("distributed plan lacks its frequency-job identity")
    manifest_path = job_dir / "job_manifest.json"
    input_path = job_dir / "input.dat"
    if (
        not manifest_path.is_file()
        or not input_path.is_file()
        or _sha256(manifest_path) != record.get("sha256")
        or _sha256(input_path) != record.get("input_sha256")
    ):
        raise ValueError(
            "job directory is not a byte-identical copy of the distributed plan's "
            "frequency job"
        )
    declared_path = Path(str(record.get("path") or ""))
    return {
        "effective_manifest_path": str(manifest_path.resolve()),
        "declared_manifest_path": str(declared_path),
        "relocated": declared_path.resolve() != manifest_path.resolve(),
        "manifest_sha256": record["sha256"],
        "input_sha256": record["input_sha256"],
    }


def _validate_existing_assembly(
    *, plan_path: Path, plan: dict[str, Any], root: Path, job_dir: Path
) -> dict[str, Any]:
    """Revalidate an immutable completed assembly after a post-assembly audit failure."""

    audit_path = root / "distributed_hessian_audit.json"
    run_path = job_dir / "run_manifest.json"
    hessian_path = job_dir / "hessian_hartree_per_bohr2.txt"
    output_path = job_dir / "output.dat"
    result_path = job_dir / "distributed_qcschema_result.json"
    required = (audit_path, run_path, hessian_path, output_path, result_path)
    if not all(path.is_file() for path in required):
        raise ValueError("existing distributed assembly is incomplete")
    assembly = json.loads(audit_path.read_text())
    run = json.loads(run_path.read_text())
    tasks = assembly.get("tasks") or []
    if (
        assembly.get("schema")
        != "nadoc.photoproduct-distributed-hessian-audit.v1"
        or assembly.get("status") != "assembled_unreviewed"
        or assembly.get("gate_effect") != "none"
        or assembly.get("product_id") != plan.get("product_id")
        or assembly.get("model_id") != plan.get("model_id")
        or assembly.get("task_count") != plan.get("task_count")
        or len(tasks) != plan.get("task_count")
        or [item.get("id") for item in tasks]
        != [item.get("id") for item in plan["tasks"]]
        or assembly.get("frequency_job_run_manifest_sha256") != _sha256(run_path)
        or (assembly.get("hessian") or {}).get("sha256") != _sha256(hessian_path)
        or Path(str((assembly.get("hessian") or {}).get("path") or "")).resolve()
        != hessian_path.resolve()
    ):
        raise ValueError("existing distributed assembly report is stale or mismatched")
    if (
        run.get("schema") != "nadoc.photoproduct-qm-run.v1"
        or run.get("status") != "completed_unreviewed"
        or run.get("gate_effect") != "none"
        or run.get("job_manifest_sha256") != _sha256(job_dir / "job_manifest.json")
        or (run.get("distributed_hessian_plan") or {}).get("sha256")
        != _sha256(plan_path)
    ):
        raise ValueError("existing distributed assembly run record is stale or mismatched")
    for name, path in {
        "output.dat": output_path,
        "hessian_hartree_per_bohr2.txt": hessian_path,
        "distributed_qcschema_result.json": result_path,
    }.items():
        if (run.get("outputs") or {}).get(name, {}).get("sha256") != _sha256(path):
            raise ValueError(f"existing assembled {name} is hash-mismatched")
    for planned, audited in zip(plan["tasks"], tasks, strict=True):
        if _completion_state(
            plan_path=plan_path, root=root, task=planned
        ) != "complete":  # pragma: no cover - non-complete raises above
            raise ValueError(f"existing task is incomplete: {planned['id']}")
        result = (root / planned["result"]["path"]).resolve()
        task_run = (root / planned["run_record"]["path"]).resolve()
        if (
            audited.get("input_sha256") != planned["input"]["sha256"]
            or audited.get("result_sha256") != _sha256(result)
            or audited.get("run_record_sha256") != _sha256(task_run)
        ):
            raise ValueError(
                f"existing assembly task evidence changed: {planned['id']}"
            )
    return assembly


def _run_task(
    *,
    task: dict[str, Any],
    plan_path: Path,
    root: Path,
    qm_python: Path,
    scratch_root: Path,
    threads: int,
    memory_gib: int,
) -> dict[str, Any]:
    task_dir = (root / task["result"]["path"]).resolve().parent
    task_scratch = (scratch_root / task["id"]).resolve()
    task_scratch.mkdir(parents=True, exist_ok=True)
    attempt = os.getpid()
    stdout_path = task_dir / f"local_runner.{attempt}.stdout"
    stderr_path = task_dir / f"local_runner.{attempt}.stderr"
    command = [
        str(qm_python),
        "-m",
        "backend.parameterization.photoproduct_distributed_hessian",
        "run-task",
        "--plan",
        str(plan_path),
        "--task-id",
        task["id"],
        "--scratch-dir",
        str(task_scratch),
        "--threads",
        str(threads),
        "--memory-gib",
        str(memory_gib),
    ]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    started = time.monotonic()
    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        completed = subprocess.run(
            command,
            # Psi4 writes timer.dat and *.clean housekeeping files to cwd even
            # when PSIO/QCEngine scratch is configured.  Keep those bulk-run
            # side effects with the task scratch, never in the repository.
            cwd=task_scratch,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            f"task {task['id']} exited {completed.returncode}; see {stderr_path}"
        )
    if _completion_state(plan_path=plan_path, root=root, task=task) != "complete":
        raise RuntimeError(f"task {task['id']} returned without a complete result pair")
    return {
        "task_id": task["id"],
        "elapsed_seconds": time.monotonic() - started,
        "working_directory": str(task_scratch),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
    }


def run_local_batch(args: argparse.Namespace) -> dict[str, Any]:
    plan_path = args.plan.resolve()
    job_dir = args.job_dir.resolve()
    scratch_root = args.scratch_root.resolve()
    output_path = args.output.resolve()
    waiting_requested = bool(args.wait_for_report or args.wait_for_service)
    if waiting_requested and not (args.wait_for_report and args.wait_for_service):
        raise ValueError("--wait-for-report and --wait-for-service must be used together")
    storage = (
        _validate_storage_root(
            args.storage_root,
            paths={
                "plan": plan_path,
                "job_dir": job_dir,
                "scratch_root": scratch_root,
                "output": output_path,
                **(
                    {"predecessor_report": args.wait_for_report.resolve()}
                    if waiting_requested
                    else {}
                ),
            },
        )
        if args.storage_root is not None
        else None
    )
    predecessor = (
        _wait_for_passed_predecessor(
            report_path=args.wait_for_report.resolve(),
            service=args.wait_for_service,
            poll_seconds=args.wait_poll_seconds,
        )
        if waiting_requested
        else None
    )
    started_at = _utc_now()
    started = time.monotonic()
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite local-batch report: {output_path}")
    if not args.qm_python.is_file():
        raise FileNotFoundError(f"pinned QM Python is missing: {args.qm_python}")
    if args.max_parallel < 1 or args.threads < 1 or args.memory_gib < 1:
        raise ValueError("parallelism, threads, and memory must be positive")
    plan, root = _load_plan(plan_path)
    frequency_job_copy = _validate_frequency_job_copy(plan=plan, job_dir=job_dir)
    states = {
        task["id"]: _completion_state(plan_path=plan_path, root=root, task=task)
        for task in plan["tasks"]
    }
    pending = [task for task in plan["tasks"] if states[task["id"]] == "pending"]
    reused_count = len(plan["tasks"]) - len(pending)
    scratch_root.mkdir(parents=True, exist_ok=True)
    completed_records: list[dict[str, Any]] = []
    failure = None
    assembly = None
    frequency = None
    try:
        print(
            f"{plan['product_id']}: {reused_count} complete, {len(pending)} pending; "
            f"running {args.max_parallel} workers",
            flush=True,
        )
        executor = ThreadPoolExecutor(max_workers=args.max_parallel)
        futures = {}
        try:
            futures = {
                executor.submit(
                    _run_task,
                    task=task,
                    plan_path=plan_path,
                    root=root,
                    qm_python=args.qm_python.resolve(),
                    scratch_root=scratch_root,
                    threads=args.threads,
                    memory_gib=args.memory_gib,
                ): task["id"]
                for task in pending
            }
            for future in as_completed(futures):
                record = future.result()
                completed_records.append(record)
                print(
                    f"completed {record['task_id']} "
                    f"({reused_count + len(completed_records)}/{plan['task_count']})",
                    flush=True,
                )
        except Exception:
            for future in futures:
                future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)
        audit_path = root / "distributed_hessian_audit.json"
        if audit_path.exists():
            assembly = _validate_existing_assembly(
                plan_path=plan_path,
                plan=plan,
                root=root,
                job_dir=job_dir,
            )
        else:
            assembly = assemble_distributed_hessian(
                job_dir=job_dir,
                plan_path=plan_path,
                output_path=audit_path,
            )
        frequency = audit_frequency_result(job_dir)
        if frequency.get("status") != "passed_candidate_harmonic_minimum":
            raise RuntimeError("assembled frequency did not pass the harmonic-minimum audit")
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report = {
            "schema": "nadoc.photoproduct-local-hessian-batch.v1",
            "status": "passed" if frequency is not None and failure is None else "failed",
            "gate_effect": "none",
            "product_id": plan["product_id"],
            "model_id": plan["model_id"],
            "started_at": started_at,
            "finished_at": _utc_now(),
            "elapsed_seconds": time.monotonic() - started,
            "plan": {"path": str(plan_path), "sha256": _sha256(plan_path)},
            "predecessor": predecessor,
            "frequency_job_copy": frequency_job_copy,
            "resources": {
                "max_parallel": args.max_parallel,
                "threads_per_task": args.threads,
                "memory_gib_per_task": args.memory_gib,
                "host": platform.node(),
                "scratch_root": str(scratch_root),
                "task_process_working_directory": "<scratch_root>/<task_id>",
                "storage_confinement": storage,
            },
            "task_count": plan["task_count"],
            "reused_task_count": reused_count,
            "newly_completed_task_count": len(completed_records),
            "assembly": (
                {
                    "path": str((root / "distributed_hessian_audit.json").resolve()),
                    "sha256": _sha256(root / "distributed_hessian_audit.json"),
                    "status": assembly["status"],
                }
                if assembly is not None
                else None
            ),
            "frequency_audit": (
                {
                    "path": str((job_dir / "frequency_audit.json").resolve()),
                    "sha256": _sha256(job_dir / "frequency_audit.json"),
                    "status": frequency["status"],
                }
                if frequency is not None
                else None
            ),
            "error": failure,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not output_path.exists():
            output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--qm-python",
        type=Path,
        default=Path("/home/jojo/miniforge3/envs/nadoc-qm/bin/python"),
    )
    parser.add_argument("--max-parallel", type=int, default=4)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--memory-gib", type=int, default=4)
    parser.add_argument(
        "--storage-root",
        type=Path,
        help=(
            "Fail closed unless plan, job, scratch, output, and predecessor report "
            "paths are all below this persistent storage root."
        ),
    )
    parser.add_argument(
        "--wait-for-report",
        type=Path,
        help="Wait for this predecessor local-batch report before starting.",
    )
    parser.add_argument(
        "--wait-for-service",
        help="User-systemd service that must stop before --wait-for-report is checked.",
    )
    parser.add_argument("--wait-poll-seconds", type=float, default=30.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = run_local_batch(args)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
