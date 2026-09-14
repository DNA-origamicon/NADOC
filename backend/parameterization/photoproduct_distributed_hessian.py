"""Hash-linked finite-difference Hessians that can run as independent Psi4 tasks.

The ordinary Psi4 ``frequency()`` driver evaluates displaced gradients serially.  This
module exposes the same Psi4 1.11 ``FiniteDifferenceComputer`` plan as immutable QCSchema
inputs so independent CPU workers can evaluate it without changing method, basis, or
finite-difference geometry.  Assembly recreates the plan, compares every input byte-for-
byte, and only then emits the conventional NADOC frequency artifacts.

All functions are gate-neutral.  Psi4/QCEngine imports are deliberately lazy because the
main NADOC environment does not contain the separate, pinned QM toolchain.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time
from typing import Any

import numpy as np

from backend.parameterization.photoproduct_qm import (
    QM_PROTOCOL_PATH,
    parse_xyz,
    qm_protocol,
    render_psi4_input,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _protocol_path_for_job(job: dict[str, Any]) -> Path:
    version = str(job.get("protocol_version") or "")
    candidate = QM_PROTOCOL_PATH.with_name(
        f"photoproduct_qm_protocol_v{version}.json"
    )
    if not candidate.is_file() or _sha256(candidate) != job.get("protocol_sha256"):
        raise ValueError("frequency job's immutable QM protocol is unavailable or changed")
    return candidate


def _relocated_frequency_reference(
    *, job_dir: Path, job: dict[str, Any], key: str, label: str
) -> Path | None:
    relocation_path = job_dir / "frequency_job_provenance.json"
    if not relocation_path.exists():
        return None
    relocation = json.loads(relocation_path.read_text())
    job_path = job_dir / "job_manifest.json"
    if (
        relocation.get("schema")
        != "nadoc.photoproduct-frequency-job-provenance-copy.v1"
        or relocation.get("status") != "materialized_byte_identical"
        or relocation.get("gate_effect") != "none"
        or (relocation.get("frequency_job_manifest") or {}).get("sha256")
        != _sha256(job_path)
    ):
        raise ValueError("frequency-job provenance-copy manifest is invalid")
    source_record = job.get(key)
    relocated_record = (relocation.get("references") or {}).get(key)
    if not isinstance(source_record, dict) or not isinstance(relocated_record, dict):
        raise ValueError(f"frequency-job provenance copy lacks {label}")
    copy_record = relocated_record.get("copy")
    if (
        relocated_record.get("original_path") != source_record.get("path")
        or relocated_record.get("sha256") != source_record.get("sha256")
        or not isinstance(copy_record, dict)
        or copy_record.get("sha256") != source_record.get("sha256")
    ):
        raise ValueError(f"frequency-job provenance copy changed {label} identity")
    copy_path = (job_dir / str(copy_record.get("path") or "")).resolve()
    try:
        copy_path.relative_to(job_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"relocated {label} escapes the frequency job") from exc
    if not copy_path.is_file() or _sha256(copy_path) != source_record.get("sha256"):
        raise ValueError(f"relocated {label} is missing or hash-mismatched")
    return copy_path


def _frequency_reference(
    *,
    job_dir: Path,
    job: dict[str, Any],
    key: str,
    label: str,
    fallback_path: Path | None = None,
) -> Path:
    relocated = _relocated_frequency_reference(
        job_dir=job_dir, job=job, key=key, label=label
    )
    if relocated is not None:
        return relocated
    record = job.get(key)
    if not isinstance(record, dict):
        raise ValueError(f"frequency job lacks {label}")
    path = Path(str(record.get("path") or ""))
    if path.is_file() and _sha256(path) == record.get("sha256"):
        return path.resolve()
    if fallback_path is not None:
        fallback = fallback_path.resolve()
        if fallback.is_file() and _sha256(fallback) == record.get("sha256"):
            return fallback
    raise ValueError(f"{label} is missing or hash-mismatched")


def _validated_frequency_job(
    job_dir: Path,
    *,
    source_xyz_fallback: Path | None = None,
    parent_manifest_fallback: Path | None = None,
    allow_execution_evidence: bool = False,
) -> tuple[dict[str, Any], Path, Path]:
    job_path = job_dir / "job_manifest.json"
    input_path = job_dir / "input.dat"
    if not job_path.is_file() or not input_path.is_file():
        raise ValueError("generated frequency job manifest and input are required")
    job = json.loads(job_path.read_text())
    if (
        job.get("schema") != "nadoc.photoproduct-qm-job.v1"
        or job.get("status") != "generated_not_run"
        or job.get("gate_effect") != "none"
        or job.get("job_kind") != "frequency"
    ):
        raise ValueError("distributed Hessian requires a neutral generated frequency job")
    if _sha256(input_path) != (job.get("input") or {}).get("sha256"):
        raise ValueError("frequency input digest no longer matches its job manifest")
    if not allow_execution_evidence and any(
        (job_dir / name).exists() for name in ("output.dat", "run_manifest.json")
    ):
        raise FileExistsError("frequency job already has execution evidence")
    source_path = _frequency_reference(
        job_dir=job_dir,
        job=job,
        key="source_xyz",
        label="frequency source geometry",
        fallback_path=source_xyz_fallback,
    )
    atom_map = job.get("atom_map")
    if (
        not isinstance(atom_map, list)
        or len(atom_map) != job.get("atom_count")
        or len(atom_map) != len(set(atom_map))
    ):
        raise ValueError("frequency job requires a unique stable atom map")
    parent_path = _frequency_reference(
        job_dir=job_dir,
        job=job,
        key="parent_manifest",
        label="optimized-model parent",
        fallback_path=parent_manifest_fallback,
    )
    parent = json.loads(parent_path.read_text())
    if (
        parent.get("schema") != "nadoc.photoproduct-optimized-model-audit.v1"
        or parent.get("status")
        not in {
            "passed_identity_and_chirality",
            "passed_candidate_identity_and_chirality",
        }
        or parent.get("product_id") != job.get("product_id")
        or parent.get("model_id") != job.get("model_id")
        or (parent.get("optimized_xyz") or {}).get("sha256") != _sha256(source_path)
    ):
        raise ValueError("frequency parent is not a passed matching optimized model")
    protocol_path = _protocol_path_for_job(job)
    rendered, metadata = render_psi4_input(
        source_path.read_text(),
        job_kind="frequency",
        charge=int(job["charge"]),
        multiplicity=int(job["multiplicity"]),
        memory_gib=int(job["memory_gib"]),
        threads=int(job["threads"]),
        protocol_path=protocol_path,
    )
    if rendered.encode() != input_path.read_bytes() or any(
        metadata.get(key) != job.get(key)
        for key in (
            "method",
            "basis",
            "charge",
            "multiplicity",
            "atom_count",
            "protocol_version",
            "protocol_sha256",
        )
    ):
        raise ValueError("frequency input cannot be reproduced from its pinned protocol")
    return job, source_path, protocol_path


def materialize_frequency_job_provenance(
    *,
    job_dir: Path,
    source_xyz_fallback: Path | None = None,
    parent_manifest_fallback: Path | None = None,
) -> dict[str, Any]:
    """Copy immutable source/parent evidence into a relocatable frequency job."""

    relocation_path = job_dir / "frequency_job_provenance.json"
    provenance_dir = job_dir / "provenance"
    if relocation_path.exists() or provenance_dir.exists():
        raise FileExistsError(
            f"refusing to overwrite frequency-job provenance copy in {job_dir}"
        )
    job, source_path, _protocol_path = _validated_frequency_job(
        job_dir,
        source_xyz_fallback=source_xyz_fallback,
        parent_manifest_fallback=parent_manifest_fallback,
        allow_execution_evidence=True,
    )
    parent_path = _frequency_reference(
        job_dir=job_dir,
        job=job,
        key="parent_manifest",
        label="optimized-model parent",
        fallback_path=parent_manifest_fallback,
    )
    source_suffix = source_path.suffix or ".dat"
    copies = {
        "source_xyz": provenance_dir / f"source_geometry{source_suffix}",
        "parent_manifest": provenance_dir / "optimized_model_parent.json",
    }
    provenance_dir.mkdir(parents=True)
    shutil.copy2(source_path, copies["source_xyz"])
    shutil.copy2(parent_path, copies["parent_manifest"])
    references = {}
    for key, source in (("source_xyz", source_path), ("parent_manifest", parent_path)):
        record = job[key]
        copy = copies[key]
        if _sha256(copy) != record["sha256"]:
            raise ValueError(f"materialized {key} differs from its immutable source")
        references[key] = {
            "original_path": record["path"],
            "sha256": record["sha256"],
            "copy": {
                "path": str(copy.relative_to(job_dir)),
                "sha256": _sha256(copy),
            },
        }
    manifest = {
        "schema": "nadoc.photoproduct-frequency-job-provenance-copy.v1",
        "status": "materialized_byte_identical",
        "gate_effect": "none",
        "product_id": job["product_id"],
        "model_id": job["model_id"],
        "frequency_job_manifest": {
            "path": "job_manifest.json",
            "sha256": _sha256(job_dir / "job_manifest.json"),
        },
        "references": references,
        "interpretation": (
            "These are byte-identical provenance copies for relocation and assembly. "
            "They do not alter the immutable QM job or advance a scientific gate."
        ),
    }
    relocation_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _require_qm_stack():
    try:
        import psi4
        import qcelemental
        from qcelemental.models.v2 import AtomicInput, AtomicResult
        import qcengine
    except ImportError as exc:  # pragma: no cover - depends on separate conda environment
        raise RuntimeError(
            "distributed Hessians require the pinned nadoc-qm environment "
            "(Psi4, QCEngine, and QCEElemental)"
        ) from exc
    return psi4, qcelemental, AtomicInput, AtomicResult, qcengine


def _configure_psi4_scratch(psi4: Any, scratch_dir: Path) -> Path:
    """Pin both Psi4's process-global PSIO path and its environment contract."""

    resolved = scratch_dir.resolve()
    if not resolved.is_dir():
        raise ValueError("Psi4 scratch directory must already exist")
    os.environ["PSI_SCRATCH"] = str(resolved)
    manager = psi4.core.IOManager.shared_object()
    manager.set_default_path(str(resolved))
    observed = Path(str(manager.get_default_path())).resolve()
    if observed != resolved:
        raise RuntimeError(
            f"Psi4 refused the requested Archive scratch path: {observed} != {resolved}"
        )
    return observed


def _build_plan(job: dict[str, Any], source_path: Path, protocol_path: Path):
    psi4, _qcelemental, _atomic_input, _atomic_result, _qcengine = _require_qm_stack()
    atoms, _comment = parse_xyz(source_path.read_text())
    coordinates = "\n".join(
        f"  {element:<2} {x: .12f} {y: .12f} {z: .12f}"
        for element, x, y, z in atoms
    )
    protocol = qm_protocol(protocol_path)
    settings = {
        "basis": job["basis"],
        "reference": "rhf" if int(job["multiplicity"]) == 1 else "uhf",
        "scf_type": protocol["jobs"]["frequency"].get("scf_type", "df"),
        "freeze_core": bool(protocol["jobs"]["frequency"].get("freeze_core", True)),
    }
    if protocol["jobs"]["frequency"].get("mp2_type"):
        settings["mp2_type"] = protocol["jobs"]["frequency"]["mp2_type"]
    psi4.core.clean()
    psi4.core.clean_options()
    psi4.set_memory(f"{int(job['memory_gib'])} GiB")
    psi4.set_num_threads(int(job["threads"]))
    molecule = psi4.geometry(
        f"{int(job['charge'])} {int(job['multiplicity'])}\n"
        f"{coordinates}\nunits angstrom\nno_com\nno_reorient\n"
    )
    psi4.set_options(settings)
    plan = psi4.hessian(job["method"], molecule=molecule, return_plan=True)
    if plan.__class__.__name__ != "FiniteDifferenceComputer":
        raise ValueError("pinned frequency method did not produce a finite-difference plan")
    if any(
        task.plan().specification.driver.value != "gradient"
        for task in plan.task_list.values()
    ):
        raise ValueError("frequency plan is not a finite difference of analytic gradients")
    return plan, molecule


def _task_slug(index: int, label: str) -> str:
    suffix = re.sub(r"[^a-zA-Z0-9]+", "-", label).strip("-").lower() or "task"
    return f"{index:04d}-{suffix}"


def prepare_distributed_hessian(*, job_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Export the exact Psi4 finite-difference plan as independently runnable tasks."""

    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise FileExistsError(f"refusing to overwrite distributed Hessian plan: {output_dir}")
    job, source_path, protocol_path = _validated_frequency_job(job_dir)
    plan, molecule = _build_plan(job, source_path, protocol_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    task_records = []
    for index, (label, task) in enumerate(plan.task_list.items()):
        task_id = _task_slug(index, label)
        task_dir = output_dir / "tasks" / task_id
        task_dir.mkdir(parents=True)
        input_path = task_dir / "input.json"
        input_path.write_bytes(
            _canonical_json_bytes(task.plan().model_dump(mode="json"))
        )
        task_records.append(
            {
                "id": task_id,
                "label": label,
                "driver": task.plan().specification.driver.value,
                "input": {
                    "path": str(input_path.relative_to(output_dir)),
                    "sha256": _sha256(input_path),
                },
                "result": {"path": str((task_dir / "result.json").relative_to(output_dir))},
                "run_record": {
                    "path": str((task_dir / "run_record.json").relative_to(output_dir))
                },
            }
        )
    psi4, qcelemental, _atomic_input, _atomic_result, qcengine = _require_qm_stack()
    manifest = {
        "schema": "nadoc.photoproduct-distributed-hessian-plan.v1",
        "status": "prepared_not_run",
        "gate_effect": "none",
        "product_id": job["product_id"],
        "model_id": job["model_id"],
        "frequency_job": {
            "path": str((job_dir / "job_manifest.json").resolve()),
            "sha256": _sha256(job_dir / "job_manifest.json"),
            "input_sha256": _sha256(job_dir / "input.dat"),
        },
        "protocol": {
            "version": job["protocol_version"],
            "sha256": _sha256(protocol_path),
        },
        "engine": {
            "name": "Psi4",
            "version": str(psi4.__version__),
            "qcengine_version": str(qcengine.__version__),
            "qcelemental_version": str(qcelemental.__version__),
            "execution_api": "QCEngine/QCSchema",
        },
        "method": job["method"],
        "basis": job["basis"],
        "atom_count": job["atom_count"],
        "task_count": len(task_records),
        "finite_difference": {
            "mode": plan.metameta["mode"],
            "stencil_size": plan.findifrec["stencil_size"],
            "step": plan.findifrec["step"],
            "molecular_point_group": molecule.schoenflies_symbol(),
        },
        "default_resources_per_task": {
            "threads": job["threads"],
            "memory_gib": job["memory_gib"],
        },
        "tasks": task_records,
        "execution_note": (
            "Tasks may run in any order and on different CPU hosts with the pinned "
            "environment. Assembly recreates and byte-compares every QCSchema input."
        ),
    }
    manifest_path = output_dir / "distributed_hessian_plan.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _load_plan(plan_path: Path) -> tuple[dict[str, Any], Path]:
    plan = json.loads(plan_path.read_text())
    if (
        plan.get("schema") != "nadoc.photoproduct-distributed-hessian-plan.v1"
        or plan.get("status") != "prepared_not_run"
        or plan.get("gate_effect") != "none"
        or not isinstance(plan.get("tasks"), list)
        or len(plan["tasks"]) != plan.get("task_count")
    ):
        raise ValueError("unsupported or malformed distributed Hessian plan")
    root = plan_path.parent.resolve()
    for task in plan["tasks"]:
        input_path = (root / task["input"]["path"]).resolve()
        input_path.relative_to(root)
        if not input_path.is_file() or _sha256(input_path) != task["input"]["sha256"]:
            raise ValueError(f"distributed Hessian task input changed: {task.get('id')}")
    return plan, root


def _completed_task_pair(
    *, plan_path: Path, root: Path, task: dict[str, Any]
) -> tuple[Path, Path] | None:
    result_path = (root / task["result"]["path"]).resolve()
    run_path = (root / task["run_record"]["path"]).resolve()
    result_path.relative_to(root)
    run_path.relative_to(root)
    if result_path.exists() != run_path.exists():
        raise ValueError(f"task has an incomplete result/run-record pair: {task['id']}")
    if not result_path.exists():
        return None
    run = json.loads(run_path.read_text())
    result = json.loads(result_path.read_text())
    if (
        run.get("schema") != "nadoc.photoproduct-distributed-hessian-task-run.v1"
        or run.get("status") != "completed_unreviewed"
        or run.get("gate_effect") != "none"
        or run.get("plan_sha256") != _sha256(plan_path)
        or run.get("task_id") != task["id"]
        or run.get("input_sha256") != task["input"]["sha256"]
        or (run.get("result") or {}).get("sha256") != _sha256(result_path)
        or not isinstance(result, dict)
        or result.get("success") is not True
    ):
        raise ValueError(f"task result pair is not safely checkpointable: {task['id']}")
    return result_path, run_path


def checkpoint_distributed_hessian_pairs(
    *, source_plan_path: Path, destination_plan_path: Path, output_path: Path
) -> dict[str, Any]:
    """Copy only complete immutable task pairs into an identical Archive plan."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite checkpoint report: {output_path}")
    source_plan, source_root = _load_plan(source_plan_path)
    destination_plan, destination_root = _load_plan(destination_plan_path)
    source_hash = _sha256(source_plan_path)
    destination_hash = _sha256(destination_plan_path)
    if (
        source_hash != destination_hash
        or source_plan != destination_plan
        or source_plan_path.resolve() == destination_plan_path.resolve()
    ):
        raise ValueError("checkpoint source and destination must be distinct identical plans")

    copied: list[dict[str, Any]] = []
    reused: list[str] = []
    pending: list[str] = []
    for source_task, destination_task in zip(
        source_plan["tasks"], destination_plan["tasks"], strict=True
    ):
        if source_task != destination_task:
            raise ValueError("checkpoint plans contain different task records")
        source_pair = _completed_task_pair(
            plan_path=source_plan_path, root=source_root, task=source_task
        )
        destination_pair = _completed_task_pair(
            plan_path=destination_plan_path,
            root=destination_root,
            task=destination_task,
        )
        if source_pair is None:
            if destination_pair is not None:
                raise ValueError(
                    f"destination contains task absent from source: {source_task['id']}"
                )
            pending.append(source_task["id"])
            continue
        if destination_pair is not None:
            if any(
                source.read_bytes() != destination.read_bytes()
                for source, destination in zip(
                    source_pair, destination_pair, strict=True
                )
            ):
                raise ValueError(
                    f"destination task differs from source: {source_task['id']}"
                )
            reused.append(source_task["id"])
            continue

        destination_result = (
            destination_root / destination_task["result"]["path"]
        ).resolve()
        destination_run = (
            destination_root / destination_task["run_record"]["path"]
        ).resolve()
        temporary_result = destination_result.with_name(
            destination_result.name + ".checkpoint-partial"
        )
        temporary_run = destination_run.with_name(
            destination_run.name + ".checkpoint-partial"
        )
        if temporary_result.exists() or temporary_run.exists():
            raise FileExistsError(
                f"stale checkpoint partial exists for task {source_task['id']}"
            )
        shutil.copy2(source_pair[0], temporary_result)
        shutil.copy2(source_pair[1], temporary_run)
        if (
            _sha256(temporary_result) != _sha256(source_pair[0])
            or _sha256(temporary_run) != _sha256(source_pair[1])
        ):
            raise ValueError(f"checkpoint copy changed task {source_task['id']}")
        temporary_result.rename(destination_result)
        temporary_run.rename(destination_run)
        copied.append(
            {
                "task_id": source_task["id"],
                "result_sha256": _sha256(destination_result),
                "run_record_sha256": _sha256(destination_run),
            }
        )

    report = {
        "schema": "nadoc.photoproduct-distributed-hessian-checkpoint.v1",
        "status": "complete_pairs_checkpointed",
        "gate_effect": "none",
        "product_id": source_plan["product_id"],
        "model_id": source_plan["model_id"],
        "task_count": source_plan["task_count"],
        "copied_pair_count": len(copied),
        "reused_pair_count": len(reused),
        "pending_pair_count": len(pending),
        "source_plan": {
            "path": str(source_plan_path.resolve()),
            "sha256": source_hash,
        },
        "destination_plan": {
            "path": str(destination_plan_path.resolve()),
            "sha256": destination_hash,
        },
        "copied_pairs": copied,
        "reused_task_ids": reused,
        "pending_task_ids": pending,
        "interpretation": (
            "Only complete hash-valid result/run-record pairs were copied. This is a "
            "storage checkpoint and has no scientific gate effect."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def reconcile_equivalent_distributed_hessian_pairs(
    *, source_plan_path: Path, destination_plan_path: Path, output_path: Path
) -> dict[str, Any]:
    """Rebind completed task results to a regenerated, byte-equivalent QM plan.

    This is intentionally narrower than a general migration.  It permits only the
    reviewed-conformer policy record and the fixed-job file locations/hashes to change;
    the reviewed conformers, generated Psi4 job, finite-difference plan, and every
    QCSchema task input must otherwise be identical.  New run records explicitly retain
    the source execution evidence instead of pretending that the tasks were rerun.
    """

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite reconciliation: {output_path}")
    source_plan, source_root = _load_plan(source_plan_path)
    destination_plan, destination_root = _load_plan(destination_plan_path)
    if source_plan_path.resolve() == destination_plan_path.resolve():
        raise ValueError("source and destination plans must be distinct")
    if source_plan.get("job_kind") != "fixed_geometry_hessian" or destination_plan.get(
        "job_kind"
    ) != "fixed_geometry_hessian":
        raise ValueError("policy reconciliation requires fixed-geometry Hessian plans")

    source_plan_hash = _sha256(source_plan_path)
    destination_plan_hash = _sha256(destination_plan_path)

    def checked_record_path(record: Any, label: str) -> Path:
        if not isinstance(record, dict):
            raise ValueError(f"plan lacks {label}")
        path = Path(str(record.get("path") or ""))
        if not path.is_file() or _sha256(path) != record.get("sha256"):
            raise ValueError(f"{label} is missing or hash-mismatched")
        return path.resolve()

    source_job_path = checked_record_path(
        source_plan.get("fixed_geometry_hessian_job"), "source fixed-geometry job"
    )
    destination_job_path = checked_record_path(
        destination_plan.get("fixed_geometry_hessian_job"),
        "destination fixed-geometry job",
    )
    source_review_path = checked_record_path(
        source_plan.get("reviewed_coupled_conformer_plan"),
        "source coupled-conformer plan",
    )
    destination_review_path = checked_record_path(
        destination_plan.get("reviewed_coupled_conformer_plan"),
        "destination coupled-conformer plan",
    )

    source_job = json.loads(source_job_path.read_text())
    destination_job = json.loads(destination_job_path.read_text())
    source_job_normalized = deepcopy(source_job)
    destination_job_normalized = deepcopy(destination_job)
    for payload in (source_job_normalized, destination_job_normalized):
        payload.pop("coupled_conformer_plan", None)
        if isinstance(payload.get("input"), dict):
            payload["input"].pop("path", None)
    if source_job_normalized != destination_job_normalized:
        raise ValueError("regenerated fixed-geometry QM jobs are not scientifically identical")
    source_input = source_job_path.parent / "input.dat"
    destination_input = destination_job_path.parent / "input.dat"
    if (
        not source_input.is_file()
        or not destination_input.is_file()
        or source_input.read_bytes() != destination_input.read_bytes()
    ):
        raise ValueError("regenerated fixed-geometry Psi4 inputs are not byte-identical")

    source_review = json.loads(source_review_path.read_text())
    destination_review = json.loads(destination_review_path.read_text())
    source_screen = (source_review.get("quantitative_screening") or {}).get(
        "policy_source"
    ) or {}
    destination_screen = (destination_review.get("quantitative_screening") or {}).get(
        "policy_source"
    ) or {}
    source_review_normalized = deepcopy(source_review)
    destination_review_normalized = deepcopy(destination_review)
    for payload in (source_review_normalized, destination_review_normalized):
        screening = payload.get("quantitative_screening") or {}
        screening.pop("policy_source", None)
    if source_review_normalized != destination_review_normalized:
        raise ValueError(
            "coupled-conformer plans differ beyond their quantitative-policy source"
        )

    source_plan_normalized = deepcopy(source_plan)
    destination_plan_normalized = deepcopy(destination_plan)
    for payload in (source_plan_normalized, destination_plan_normalized):
        fixed = payload.get("fixed_geometry_hessian_job") or {}
        payload["fixed_geometry_hessian_job"] = {
            "input_sha256": fixed.get("input_sha256")
        }
        payload.pop("reviewed_coupled_conformer_plan", None)
    if source_plan_normalized != destination_plan_normalized:
        raise ValueError(
            "distributed plans differ beyond reviewed-policy and fixed-job provenance"
        )

    pairs: list[tuple[dict[str, Any], dict[str, Any], Path, Path, Path, Path]] = []
    for source_task, destination_task in zip(
        source_plan["tasks"], destination_plan["tasks"], strict=True
    ):
        source_input_path = (source_root / source_task["input"]["path"]).resolve()
        destination_input_path = (
            destination_root / destination_task["input"]["path"]
        ).resolve()
        if (
            source_task != destination_task
            or source_input_path.read_bytes() != destination_input_path.read_bytes()
        ):
            raise ValueError(
                f"QCSchema task differs after policy rollover: {source_task.get('id')}"
            )
        source_pair = _completed_task_pair(
            plan_path=source_plan_path, root=source_root, task=source_task
        )
        if source_pair is None:
            raise ValueError(f"source task is incomplete: {source_task['id']}")
        destination_result = (
            destination_root / destination_task["result"]["path"]
        ).resolve()
        destination_run = (
            destination_root / destination_task["run_record"]["path"]
        ).resolve()
        if destination_result.exists() != destination_run.exists():
            raise ValueError(
                f"destination has an incomplete task pair: {destination_task['id']}"
            )
        pairs.append(
            (
                source_task,
                destination_task,
                source_pair[0],
                source_pair[1],
                destination_result,
                destination_run,
            )
        )

    copied = []
    reused = []
    for source_task, destination_task, source_result, source_run, destination_result, destination_run in pairs:
        source_run_payload = json.loads(source_run.read_text())
        reconciliation = {
            "schema": "nadoc.photoproduct-distributed-task-plan-reconciliation.v1",
            "status": "reused_byte_identical_qcschema_result",
            "gate_effect": "none",
            "source_plan": {"path": str(source_plan_path.resolve()), "sha256": source_plan_hash},
            "source_run_record": {"path": str(source_run), "sha256": _sha256(source_run)},
            "source_result": {"path": str(source_result), "sha256": _sha256(source_result)},
            "destination_plan": {
                "path": str(destination_plan_path.resolve()),
                "sha256": destination_plan_hash,
            },
            "qcschema_input_sha256": destination_task["input"]["sha256"],
            "interpretation": (
                "The QCSchema input bytes and all scientific plan fields are identical. "
                "Only policy/file provenance changed; this record does not rerun QM or "
                "advance a force-field gate."
            ),
        }
        if destination_result.exists():
            destination_payload = json.loads(destination_run.read_text())
            if (
                destination_result.read_bytes() != source_result.read_bytes()
                or destination_payload.get("provenance_reconciliation") != reconciliation
            ):
                raise ValueError(
                    f"existing reconciled task differs: {destination_task['id']}"
                )
            _completed_task_pair(
                plan_path=destination_plan_path,
                root=destination_root,
                task=destination_task,
            )
            reused.append(destination_task["id"])
            continue

        result_partial = destination_result.with_name(
            destination_result.name + ".reconcile-partial"
        )
        run_partial = destination_run.with_name(destination_run.name + ".reconcile-partial")
        if result_partial.exists() or run_partial.exists():
            raise FileExistsError(
                f"stale reconciliation partial exists: {destination_task['id']}"
            )
        shutil.copy2(source_result, result_partial)
        destination_payload = deepcopy(source_run_payload)
        destination_payload["plan_sha256"] = destination_plan_hash
        destination_payload["input_sha256"] = destination_task["input"]["sha256"]
        destination_payload["result"] = {
            **(destination_payload.get("result") or {}),
            "path": str(destination_result),
            "sha256": _sha256(result_partial),
            "bytes": result_partial.stat().st_size,
        }
        destination_payload["provenance_reconciliation"] = reconciliation
        run_partial.write_text(json.dumps(destination_payload, indent=2) + "\n")
        result_partial.rename(destination_result)
        run_partial.rename(destination_run)
        _completed_task_pair(
            plan_path=destination_plan_path,
            root=destination_root,
            task=destination_task,
        )
        copied.append(destination_task["id"])

    report = {
        "schema": "nadoc.photoproduct-distributed-plan-reconciliation.v1",
        "status": "completed_results_reused_after_policy_rollover",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_id": destination_plan["product_id"],
        "model_id": destination_plan["model_id"],
        "conformer": destination_plan["conformer"],
        "task_count": destination_plan["task_count"],
        "copied_pair_count": len(copied),
        "reused_pair_count": len(reused),
        "source_plan": {"path": str(source_plan_path.resolve()), "sha256": source_plan_hash},
        "destination_plan": {
            "path": str(destination_plan_path.resolve()),
            "sha256": destination_plan_hash,
        },
        "policy_transition": {
            "source_sha256": source_screen.get("sha256"),
            "destination_sha256": destination_screen.get("sha256"),
        },
        "fixed_geometry_input_sha256": _sha256(destination_input),
        "task_ids": copied + reused,
        "interpretation": (
            "This proves calculation-input equivalence and preserves the original "
            "execution provenance. The reused results remain unreviewed until normal "
            "assembly and response audits pass under the destination plan."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def run_distributed_hessian_task(
    *,
    plan_path: Path,
    task_id: str,
    scratch_dir: Path,
    threads: int | None = None,
    memory_gib: int | None = None,
) -> dict[str, Any]:
    """Run one immutable displaced-gradient task and hash its complete QCSchema result."""

    plan, root = _load_plan(plan_path)
    record = next((item for item in plan["tasks"] if item["id"] == task_id), None)
    if record is None:
        raise KeyError(f"unknown distributed Hessian task: {task_id}")
    result_path = (root / record["result"]["path"]).resolve()
    run_path = (root / record["run_record"]["path"]).resolve()
    result_path.relative_to(root)
    run_path.relative_to(root)
    if result_path.exists() or run_path.exists():
        raise FileExistsError(f"refusing to overwrite distributed task result: {task_id}")
    defaults = plan["default_resources_per_task"]
    threads = int(threads if threads is not None else defaults["threads"])
    memory_gib = int(memory_gib if memory_gib is not None else defaults["memory_gib"])
    if threads < 1 or memory_gib < 1:
        raise ValueError("task threads and memory must be positive")
    scratch_dir = scratch_dir.resolve()
    scratch_dir.mkdir(parents=True, exist_ok=True)
    # QCEngine's PsiAPI path does not currently apply its temporary-directory path to
    # Psi4's process-global PSIO manager. Set PSI_SCRATCH before importing Psi4, then
    # enforce the same path through the IO manager so large DF/MP2 files cannot fall
    # back to /tmp on the low-capacity system volume.
    os.environ["PSI_SCRATCH"] = str(scratch_dir)
    psi4, qcelemental, AtomicInput, _atomic_result, qcengine = _require_qm_stack()
    psi4_scratch = _configure_psi4_scratch(psi4, scratch_dir)
    observed_versions = {
        "version": str(psi4.__version__),
        "qcengine_version": str(qcengine.__version__),
        "qcelemental_version": str(qcelemental.__version__),
    }
    if any(observed_versions[key] != plan["engine"].get(key) for key in observed_versions):
        raise ValueError("QM stack version differs from the distributed plan")
    input_path = root / record["input"]["path"]
    atomic_input = AtomicInput.model_validate_json(input_path.read_text())
    started = time.monotonic()
    result = qcengine.compute(
        atomic_input,
        "psi4",
        raise_error=False,
        task_config={
            "ncores": threads,
            "memory": float(memory_gib),
            "scratch_directory": str(scratch_dir.resolve()),
            "scratch_messy": False,
        },
    )
    elapsed_seconds = time.monotonic() - started
    result_path.write_bytes(_canonical_json_bytes(result.model_dump(mode="json")))
    success = bool(getattr(result, "success", False))
    run_record = {
        "schema": "nadoc.photoproduct-distributed-hessian-task-run.v1",
        "status": "completed_unreviewed" if success else "failed",
        "gate_effect": "none",
        "plan_sha256": _sha256(plan_path),
        "task_id": task_id,
        "task_label": record["label"],
        "input_sha256": _sha256(input_path),
        "result": {
            "path": str(result_path),
            "sha256": _sha256(result_path),
            "bytes": result_path.stat().st_size,
        },
        "resources": {"threads": threads, "memory_gib": memory_gib},
        "execution": {
            "elapsed_seconds": elapsed_seconds,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "logical_cpu_count": os.cpu_count(),
            "runpod_pod_id": os.environ.get("RUNPOD_POD_ID"),
            "executable": sys.executable,
            "qcengine_scratch_directory": str(scratch_dir),
            "psi4_psio_default_path": str(psi4_scratch),
            "process_working_directory": str(Path.cwd().resolve()),
        },
        "engine": {
            "name": "Psi4",
            **observed_versions,
            "provenance": (
                result.provenance.model_dump(mode="json")
                if success and getattr(result, "provenance", None) is not None
                else None
            ),
        },
    }
    run_path.write_text(json.dumps(run_record, indent=2) + "\n")
    return run_record


def _signed_frequency(value: complex) -> float:
    if abs(value.imag) > abs(value.real):
        return -abs(float(value.imag))
    return float(value.real)


def _restore_qcengine_arrays(result: Any) -> Any:
    """Restore arrays that QCSchema JSON necessarily represented as nested lists.

    Psi4 1.11's finite-difference assembler calls NumPy methods directly on gradient and
    dipole values.  Fresh QCEngine results contain arrays, whereas a result transported
    through JSON contains lists.  The conversion is representation-only and happens
    after the stored JSON and its hash have been validated.
    """

    if result.input_data.specification.driver.value in {"gradient", "hessian"}:
        result = result.model_copy(
            update={"return_result": np.asarray(result.return_result, dtype=float)}
        )
    qcvars = result.extras.get("qcvars") or {}
    for name, value in list(qcvars.items()):
        if isinstance(value, list) and name in {
            "CURRENT DIPOLE",
            "CURRENT GRADIENT",
            "CURRENT HESSIAN",
        }:
            qcvars[name] = np.asarray(value, dtype=float)
    return result


def assemble_distributed_hessian(
    *, job_dir: Path, plan_path: Path, output_path: Path
) -> dict[str, Any]:
    """Audit all tasks, reassemble the Hessian, and emit normal NADOC job artifacts."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite distributed Hessian audit: {output_path}")
    job, source_path, protocol_path = _validated_frequency_job(job_dir)
    distributed, root = _load_plan(plan_path)
    if (
        distributed.get("frequency_job", {}).get("sha256")
        != _sha256(job_dir / "job_manifest.json")
        or distributed.get("frequency_job", {}).get("input_sha256")
        != _sha256(job_dir / "input.dat")
        or distributed.get("protocol", {}).get("sha256") != _sha256(protocol_path)
        or distributed.get("product_id") != job["product_id"]
        or distributed.get("model_id") != job["model_id"]
    ):
        raise ValueError("distributed plan does not match the frequency job")
    plan, molecule = _build_plan(job, source_path, protocol_path)
    regenerated = list(plan.task_list.items())
    if len(regenerated) != len(distributed["tasks"]):
        raise ValueError("recreated finite-difference task count changed")
    psi4, qcelemental, AtomicInput, AtomicResult, qcengine = _require_qm_stack()
    local_versions = {
        "version": str(psi4.__version__),
        "qcengine_version": str(qcengine.__version__),
        "qcelemental_version": str(qcelemental.__version__),
    }
    if any(local_versions[key] != distributed["engine"].get(key) for key in local_versions):
        raise ValueError("assembly QM stack version differs from the distributed plan")
    task_audits = []
    versions = set()
    for (label, computer), task_record in zip(
        regenerated, distributed["tasks"], strict=True
    ):
        input_path = root / task_record["input"]["path"]
        regenerated_bytes = _canonical_json_bytes(
            computer.plan().model_dump(mode="json")
        )
        if (
            label != task_record["label"]
            or regenerated_bytes != input_path.read_bytes()
            or _sha256(input_path) != task_record["input"]["sha256"]
        ):
            raise ValueError(f"recreated task differs from plan: {task_record['id']}")
        # Parsing the stored input again also rejects a syntactically invalid QCSchema task.
        AtomicInput.model_validate_json(input_path.read_text())
        result_path = root / task_record["result"]["path"]
        run_path = root / task_record["run_record"]["path"]
        if not result_path.is_file() or not run_path.is_file():
            raise FileNotFoundError(f"distributed task is incomplete: {task_record['id']}")
        run = json.loads(run_path.read_text())
        if (
            run.get("schema")
            != "nadoc.photoproduct-distributed-hessian-task-run.v1"
            or run.get("status") != "completed_unreviewed"
            or run.get("gate_effect") != "none"
            or run.get("plan_sha256") != _sha256(plan_path)
            or run.get("task_id") != task_record["id"]
            or run.get("input_sha256") != _sha256(input_path)
            or (run.get("result") or {}).get("sha256") != _sha256(result_path)
            or any(
                (run.get("engine") or {}).get(key) != distributed["engine"].get(key)
                for key in local_versions
            )
        ):
            raise ValueError(f"distributed task run record is invalid: {task_record['id']}")
        result = AtomicResult.model_validate_json(result_path.read_text())
        if (
            not result.success
            or result.input_data.model_dump(mode="json")
            != computer.plan().model_dump(mode="json")
        ):
            raise ValueError(f"distributed task result/input mismatch: {task_record['id']}")
        version = str(result.provenance.version)
        versions.add(version)
        result = _restore_qcengine_arrays(result)
        computer.result = result
        computer.computed = True
        task_audits.append(
            {
                "id": task_record["id"],
                "label": label,
                "input_sha256": _sha256(input_path),
                "result_sha256": _sha256(result_path),
                "run_record_sha256": _sha256(run_path),
                "resources": run["resources"],
                "execution": run.get("execution"),
            }
        )
    if versions != {distributed["engine"]["version"]}:
        raise ValueError("distributed tasks used an absent or inconsistent Psi4 version")
    assembled = plan.get_results()
    hessian = np.asarray(assembled.return_result, dtype=float)
    dimension = 3 * int(job["atom_count"])
    if hessian.shape != (dimension, dimension) or not np.isfinite(hessian).all():
        raise ValueError("assembled Cartesian Hessian is malformed or non-finite")
    symmetry_error = float(np.max(np.abs(hessian - hessian.T)))
    if symmetry_error > 1e-8:
        raise ValueError("assembled Cartesian Hessian exceeds symmetry tolerance")
    basis = psi4.core.BasisSet.build(
        molecule, "ORBITAL", str(job["basis"]), quiet=True
    )
    from psi4.driver.qcdb.vib import harmonic_analysis

    vibinfo, _vibtext = harmonic_analysis(
        hessian,
        np.asarray(molecule.geometry()),
        np.asarray([molecule.mass(index) for index in range(molecule.natom())]),
        basis,
        molecule.irrep_labels(),
        project_trans=True,
        project_rot=True,
    )
    frequencies = [
        _signed_frequency(complex(value))
        for value, kind in zip(vibinfo["omega"].data, vibinfo["TRV"].data, strict=True)
        if kind == "V"
    ]
    if len(frequencies) != 3 * int(job["atom_count"]) - 6 or not all(
        math.isfinite(value) for value in frequencies
    ):
        raise ValueError("assembled nonlinear-model vibrational table is incomplete")
    hessian_path = job_dir / "hessian_hartree_per_bohr2.txt"
    summary_path = job_dir / "output.dat"
    run_path = job_dir / "run_manifest.json"
    assembled_result_path = job_dir / "distributed_qcschema_result.json"
    if any(path.exists() for path in (hessian_path, summary_path, run_path, assembled_result_path)):
        raise FileExistsError("refusing to overwrite assembled frequency artifacts")
    np.savetxt(hessian_path, hessian, fmt="%.16e")
    assembled_result_path.write_bytes(
        _canonical_json_bytes(assembled.model_dump(mode="json"))
    )
    lines = [
        "NADOC distributed Psi4 finite-difference Hessian assembly",
        f"Psi4 version {next(iter(versions))}",
        f"Tasks {len(task_audits)}; method {job['method']}/{job['basis']}",
        "Projected nonlinear vibrational frequencies:",
    ]
    for index in range(0, len(frequencies), 3):
        tokens = [
            f"{abs(value):.4f}i" if value < 0 else f"{value:.4f}"
            for value in frequencies[index : index + 3]
        ]
        lines.append("  Freq [cm^-1]  " + "  ".join(tokens))
    lines.append("All displaced-gradient QCSchema results passed hash and identity audit.")
    summary_path.write_text("\n".join(lines) + "\n")
    outputs = {
        path.name: {
            "path": str(path.resolve()),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in (summary_path, hessian_path, assembled_result_path)
    }
    run_record = {
        "schema": "nadoc.photoproduct-qm-run.v1",
        "status": "completed_unreviewed",
        "gate_effect": "none",
        "job_manifest_sha256": _sha256(job_dir / "job_manifest.json"),
        "command": ["distributed-qcengine-psi4", "assemble"],
        "returncode": 0,
        "parsed": {
            "psi4_success_exit": True,
            "optimization_complete": None,
            "final_energy_hartree": float(assembled.properties.return_energy),
            "passed_execution_checks": True,
            "execution_mode": "hash-audited-distributed-finite-difference",
        },
        "outputs": outputs,
        "distributed_hessian_plan": {
            "path": str(plan_path.resolve()),
            "sha256": _sha256(plan_path),
        },
    }
    run_path.write_text(json.dumps(run_record, indent=2) + "\n")
    report = {
        "schema": "nadoc.photoproduct-distributed-hessian-audit.v1",
        "status": "assembled_unreviewed",
        "gate_effect": "none",
        "product_id": job["product_id"],
        "model_id": job["model_id"],
        "engine": {
            "name": "Psi4",
            "versions": sorted(versions),
            "qcengine_version": str(qcengine.__version__),
            "qcelemental_version": str(qcelemental.__version__),
        },
        "method": job["method"],
        "basis": job["basis"],
        "task_count": len(task_audits),
        "tasks": task_audits,
        "hessian": {
            **outputs[hessian_path.name],
            "units": "hartree/bohr^2",
            "dimension": dimension,
            "maximum_symmetry_error": symmetry_error,
        },
        "frequency_count": len(frequencies),
        "imaginary_frequency_count": sum(value < 0 for value in frequencies),
        "lowest_frequency_cm_inverse": min(frequencies),
        "frequency_job_run_manifest_sha256": _sha256(run_path),
        "release_note": (
            "Assembly reproduces Psi4's finite-difference and vibrational-analysis "
            "algorithms; the ordinary NADOC frequency audit is still required."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def _worker_main(argv: list[str] | None = None) -> int:
    """Minimal module CLI for remote workers without importing NADOC's full API stack."""

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run-task")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--task-id", required=True)
    run.add_argument("--scratch-dir", type=Path, required=True)
    run.add_argument("--threads", type=int)
    run.add_argument("--memory-gib", type=int)
    args = parser.parse_args(argv)
    result = run_distributed_hessian_task(
        plan_path=args.plan,
        task_id=args.task_id,
        scratch_dir=args.scratch_dir,
        threads=args.threads,
        memory_gib=args.memory_gib,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by real worker integration
    raise SystemExit(_worker_main())
