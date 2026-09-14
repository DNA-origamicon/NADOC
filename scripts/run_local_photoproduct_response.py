#!/usr/bin/env python3
"""Run one reviewed fixed-geometry force/Hessian as a resumable local batch."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.parameterization.photoproduct_coupled_conformer import (  # noqa: E402
    audit_fixed_geometry_hessian_result,
)
from backend.parameterization.photoproduct_distributed_response import (  # noqa: E402
    assemble_distributed_fixed_geometry_hessian,
)
from scripts.run_local_photoproduct_hessian import (  # noqa: E402
    _completion_state,
    _load_plan,
    _run_task,
    _validate_storage_root,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _validate_fixed_job_copy(
    *, plan: dict[str, Any], job_dir: Path
) -> dict[str, Any]:
    """Require the job bytes named by the distributed response plan."""

    if plan.get("job_kind") != "fixed_geometry_hessian":
        raise ValueError("local response runner requires a fixed-geometry plan")
    record = plan.get("fixed_geometry_hessian_job")
    if not isinstance(record, dict):
        raise ValueError("distributed response plan lacks its immutable job identity")
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
            "fixed-geometry job"
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
    audit_path = root / "distributed_fixed_hessian_audit.json"
    run_path = job_dir / "run_manifest.json"
    output_path = job_dir / "output.dat"
    gradient_path = job_dir / "gradient_hartree_per_bohr.txt"
    hessian_path = job_dir / "hessian_hartree_per_bohr2.txt"
    result_path = job_dir / "distributed_qcschema_result.json"
    required = (
        audit_path,
        run_path,
        output_path,
        gradient_path,
        hessian_path,
        result_path,
    )
    if not all(path.is_file() for path in required):
        raise ValueError("existing distributed fixed-geometry assembly is incomplete")
    assembly = json.loads(audit_path.read_text())
    run = json.loads(run_path.read_text())
    tasks = assembly.get("tasks") or []
    if (
        assembly.get("schema")
        != "nadoc.photoproduct-distributed-fixed-hessian-audit.v1"
        or assembly.get("status") != "assembled_unreviewed_response"
        or assembly.get("simulation_ready") is not False
        or assembly.get("gate_effect") != "none"
        or assembly.get("product_id") != plan.get("product_id")
        or assembly.get("model_id") != plan.get("model_id")
        or assembly.get("conformer_id") != (plan.get("conformer") or {}).get("id")
        or assembly.get("partition")
        != (plan.get("conformer") or {}).get("partition")
        or assembly.get("task_count") != plan.get("task_count")
        or [item.get("id") for item in tasks]
        != [item.get("id") for item in plan["tasks"]]
        or assembly.get("fixed_geometry_job_run_manifest_sha256")
        != _sha256(run_path)
        or (assembly.get("cartesian_gradient") or {}).get("sha256")
        != _sha256(gradient_path)
        or (assembly.get("cartesian_hessian") or {}).get("sha256")
        != _sha256(hessian_path)
    ):
        raise ValueError("existing distributed response report is stale or mismatched")
    if (
        run.get("schema") != "nadoc.photoproduct-qm-run.v1"
        or run.get("status") != "completed_unreviewed"
        or run.get("gate_effect") != "none"
        or run.get("job_manifest_sha256") != _sha256(job_dir / "job_manifest.json")
        or (run.get("distributed_hessian_plan") or {}).get("sha256")
        != _sha256(plan_path)
    ):
        raise ValueError("existing distributed response run record is stale")
    for artifact in (output_path, gradient_path, hessian_path, result_path):
        if (run.get("outputs") or {}).get(artifact.name, {}).get(
            "sha256"
        ) != _sha256(artifact):
            raise ValueError(f"existing assembled {artifact.name} is hash-mismatched")
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


def _validate_existing_response_audit(
    *, job_dir: Path, plan: dict[str, Any]
) -> dict[str, Any]:
    path = job_dir / "fixed_geometry_hessian_audit.json"
    if not path.is_file():
        raise ValueError("existing fixed-geometry response audit is missing")
    audit = json.loads(path.read_text())
    energy = audit.get("electronic_energy") or {}
    if (
        audit.get("schema")
        != "nadoc.photoproduct-fixed-geometry-hessian-audit.v1"
        or audit.get("status") != "passed_candidate_response_evidence"
        or audit.get("simulation_ready") is not False
        or audit.get("gate_effect") != "none"
        or audit.get("product_id") != plan.get("product_id")
        or audit.get("model_id") != plan.get("model_id")
        or audit.get("conformer_id") != (plan.get("conformer") or {}).get("id")
        or audit.get("partition") != (plan.get("conformer") or {}).get("partition")
        or (audit.get("qm_job") or {}).get("sha256")
        != _sha256(job_dir / "job_manifest.json")
        or (audit.get("effective_run_record") or {}).get("sha256")
        != _sha256(job_dir / "run_manifest.json")
        or (audit.get("cartesian_gradient") or {}).get("sha256")
        != _sha256(job_dir / "gradient_hartree_per_bohr.txt")
        or (audit.get("cartesian_hessian") or {}).get("sha256")
        != _sha256(job_dir / "hessian_hartree_per_bohr2.txt")
        or energy.get("units") != "hartree"
        or isinstance(energy.get("value"), bool)
        or not isinstance(energy.get("value"), (int, float))
        or not math.isfinite(float(energy["value"]))
        or energy.get("geometry_sha256")
        != (audit.get("source_geometry") or {}).get("sha256")
    ):
        raise ValueError("existing fixed-geometry response audit is stale or mismatched")
    return audit


def run_local_response_batch(args: argparse.Namespace) -> dict[str, Any]:
    plan_path = args.plan.resolve()
    job_dir = args.job_dir.resolve()
    scratch_root = args.scratch_root.resolve()
    output_path = args.output.resolve()
    storage = (
        _validate_storage_root(
            args.storage_root,
            paths={
                "plan": plan_path,
                "job_dir": job_dir,
                "scratch_root": scratch_root,
                "output": output_path,
            },
        )
        if args.storage_root is not None
        else None
    )
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite local response report: {output_path}")
    if not args.qm_python.is_file():
        raise FileNotFoundError(f"pinned QM Python is missing: {args.qm_python}")
    if args.max_parallel < 1 or args.threads < 1 or args.memory_gib < 1:
        raise ValueError("parallelism, threads, and memory must be positive")
    plan, root = _load_plan(plan_path)
    job_copy = _validate_fixed_job_copy(plan=plan, job_dir=job_dir)
    states = {
        task["id"]: _completion_state(plan_path=plan_path, root=root, task=task)
        for task in plan["tasks"]
    }
    pending = [task for task in plan["tasks"] if states[task["id"]] == "pending"]
    reused_count = len(plan["tasks"]) - len(pending)
    scratch_root.mkdir(parents=True, exist_ok=True)
    started_at = _utc_now()
    started = time.monotonic()
    completed_records: list[dict[str, Any]] = []
    assembly = None
    response = None
    failure = None
    try:
        print(
            f"{plan['product_id']} {plan['conformer']['id']}: {reused_count} complete, "
            f"{len(pending)} pending; running {args.max_parallel} workers",
            flush=True,
        )
        with ThreadPoolExecutor(max_workers=args.max_parallel) as executor:
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
        assembly_path = root / "distributed_fixed_hessian_audit.json"
        assembly = (
            _validate_existing_assembly(
                plan_path=plan_path, plan=plan, root=root, job_dir=job_dir
            )
            if assembly_path.exists()
            else assemble_distributed_fixed_geometry_hessian(
                job_dir=job_dir,
                plan_path=plan_path,
                output_path=assembly_path,
            )
        )
        response_path = job_dir / "fixed_geometry_hessian_audit.json"
        response = (
            _validate_existing_response_audit(job_dir=job_dir, plan=plan)
            if response_path.exists()
            else audit_fixed_geometry_hessian_result(job_dir)
        )
        if response.get("status") != "passed_candidate_response_evidence":
            raise RuntimeError("fixed-geometry derivative audit did not pass")
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report = {
            "schema": "nadoc.photoproduct-local-fixed-hessian-batch.v1",
            "status": "passed" if response is not None and failure is None else "failed",
            "simulation_ready": False,
            "gate_effect": "none",
            "product_id": plan["product_id"],
            "model_id": plan["model_id"],
            "conformer_id": plan["conformer"]["id"],
            "partition": plan["conformer"]["partition"],
            "started_at": started_at,
            "finished_at": _utc_now(),
            "elapsed_seconds": time.monotonic() - started,
            "plan": {"path": str(plan_path), "sha256": _sha256(plan_path)},
            "fixed_geometry_job_copy": job_copy,
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
                    "path": str((root / "distributed_fixed_hessian_audit.json").resolve()),
                    "sha256": _sha256(root / "distributed_fixed_hessian_audit.json"),
                    "status": assembly["status"],
                }
                if assembly is not None
                else None
            ),
            "fixed_geometry_hessian_audit": (
                {
                    "path": str(
                        (job_dir / "fixed_geometry_hessian_audit.json").resolve()
                    ),
                    "sha256": _sha256(
                        job_dir / "fixed_geometry_hessian_audit.json"
                    ),
                    "status": response["status"],
                }
                if response is not None
                else None
            ),
            "error": failure,
            "interpretation": (
                "A passed batch is gate-neutral reviewed-coordinate response evidence, "
                "not a stationary point or simulation-ready force field."
            ),
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
        help="Fail unless every job, task, scratch, and report path is under this root.",
    )
    return parser


def main() -> int:
    report = run_local_response_batch(_parser().parse_args())
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
