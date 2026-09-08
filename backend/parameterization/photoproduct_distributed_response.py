"""Distributed fixed-geometry force/Hessian targets for reviewed conformers.

Off-equilibrium photoproduct fitting needs the force and full Cartesian Hessian at an
exact, human-reviewed geometry.  Psi4 evaluates the Hessian as independent analytic
gradients, so this module exports those immutable QCSchema tasks and later recreates the
plan before assembling the response target.  It intentionally performs no vibrational
analysis: a reviewed distorted conformer is not asserted to be a stationary point.

The task records use the generic distributed-Hessian worker contract.  Imports from the
frequency distributor are representation/execution helpers only; the job validation,
protocol selection, plan construction, assembly, and output semantics here are specific
to ``fixed_geometry_hessian`` jobs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from backend.parameterization.photoproduct_coupled_conformer import (
    validate_reviewed_coupled_conformer_plan,
)
from backend.parameterization.photoproduct_distributed_hessian import (
    _canonical_json_bytes,
    _load_plan,
    _require_qm_stack,
    _restore_qcengine_arrays,
    _sha256,
    _task_slug,
)
from backend.parameterization.photoproduct_qm import (
    QM_PROTOCOL_PATH,
    parse_xyz,
    qm_protocol,
    render_psi4_input,
)


def _protocol_path_for_job(job: dict[str, Any]) -> Path:
    version = str(job.get("protocol_version") or "")
    candidate = QM_PROTOCOL_PATH.with_name(
        f"photoproduct_qm_protocol_v{version}.json"
    )
    if not candidate.is_file() or _sha256(candidate) != job.get("protocol_sha256"):
        raise ValueError(
            "fixed-geometry job's immutable QM protocol is unavailable or changed"
        )
    return candidate


def _checked_reference(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"fixed-geometry job lacks {label}")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path.resolve()


def _validated_fixed_geometry_job(
    job_dir: Path, *, allow_execution_evidence: bool = False
) -> tuple[dict[str, Any], Path, Path]:
    """Reproduce a generated fixed-geometry input and its reviewed identity chain."""

    job_path = job_dir / "job_manifest.json"
    input_path = job_dir / "input.dat"
    if not job_path.is_file() or not input_path.is_file():
        raise ValueError("generated fixed-geometry job manifest and input are required")
    job = json.loads(job_path.read_text())
    if (
        job.get("schema") != "nadoc.photoproduct-qm-job.v1"
        or job.get("status") != "generated_not_run"
        or job.get("gate_effect") != "none"
        or job.get("job_kind") != "fixed_geometry_hessian"
    ):
        raise ValueError(
            "distributed response requires a neutral generated fixed-geometry job"
        )
    if _sha256(input_path) != (job.get("input") or {}).get("sha256"):
        raise ValueError("fixed-geometry input digest no longer matches its manifest")
    if not allow_execution_evidence and any(
        (job_dir / name).exists() for name in ("output.dat", "run_manifest.json")
    ):
        raise FileExistsError("fixed-geometry job already has execution evidence")

    source_path = _checked_reference(job.get("source_xyz"), "source geometry")
    review_path = _checked_reference(
        job.get("coupled_conformer_plan"), "reviewed coupled-conformer plan"
    )
    reviewed = validate_reviewed_coupled_conformer_plan(review_path)
    conformer = job.get("conformer") or {}
    matches = [
        item
        for item in reviewed["conformers"]
        if item.get("id") == conformer.get("id")
    ]
    if len(matches) != 1:
        raise ValueError("fixed-geometry conformer is absent from its reviewed plan")
    selected = matches[0]
    if (
        reviewed["plan"].get("product_id") != job.get("product_id")
        or reviewed["plan"].get("model_id") != job.get("model_id")
        or selected["geometry"].get("sha256") != _sha256(source_path)
        or conformer.get("geometry_sha256") != _sha256(source_path)
        or conformer.get("partition") != selected.get("partition")
        or conformer.get("review_decision") != "accepted"
        or job.get("atom_map") != reviewed["atom_map"]
    ):
        raise ValueError(
            "fixed-geometry job identity, partition, geometry, or atom map differs "
            "from human review"
        )
    if job.get("coordinate_policy") != {
        "optimization": "forbidden",
        "reflection": "forbidden",
        "atom_reordering": "forbidden",
        "required_outputs": ["gradient", "full_cartesian_hessian"],
    }:
        raise ValueError("fixed-geometry coordinate policy is absent or changed")
    atom_map = job.get("atom_map")
    if (
        not isinstance(atom_map, list)
        or len(atom_map) != job.get("atom_count")
        or len(atom_map) != len(set(atom_map))
    ):
        raise ValueError("fixed-geometry job requires a unique stable atom map")

    protocol_path = _protocol_path_for_job(job)
    rendered, metadata = render_psi4_input(
        source_path.read_text(),
        job_kind="fixed_geometry_hessian",
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
        raise ValueError(
            "fixed-geometry input cannot be reproduced from its pinned protocol"
        )
    return job, source_path, protocol_path


def _build_fixed_geometry_plan(
    job: dict[str, Any], source_path: Path, protocol_path: Path
):
    psi4, _qcelemental, _atomic_input, _atomic_result, _qcengine = _require_qm_stack()
    atoms, _comment = parse_xyz(source_path.read_text())
    coordinates = "\n".join(
        f"  {element:<2} {x: .12f} {y: .12f} {z: .12f}"
        for element, x, y, z in atoms
    )
    protocol = qm_protocol(protocol_path)
    fixed = protocol["jobs"]["fixed_geometry_hessian"]
    settings = {
        "basis": job["basis"],
        "reference": "rhf" if int(job["multiplicity"]) == 1 else "uhf",
        "scf_type": fixed.get("scf_type", "df"),
        "freeze_core": bool(fixed.get("freeze_core", True)),
    }
    if fixed.get("mp2_type"):
        settings["mp2_type"] = fixed["mp2_type"]
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
        raise ValueError(
            "pinned fixed-geometry method did not produce a finite-difference plan"
        )
    if any(
        task.plan().specification.driver.value != "gradient"
        for task in plan.task_list.values()
    ):
        raise ValueError(
            "fixed-geometry Hessian is not a finite difference of analytic gradients"
        )
    return plan, molecule


def prepare_distributed_fixed_geometry_hessian(
    *, job_dir: Path, output_dir: Path
) -> dict[str, Any]:
    """Export one reviewed conformer's exact displaced-gradient plan."""

    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise FileExistsError(
            f"refusing to overwrite distributed fixed-geometry plan: {output_dir}"
        )
    job, source_path, protocol_path = _validated_fixed_geometry_job(job_dir)
    plan, molecule = _build_fixed_geometry_plan(job, source_path, protocol_path)
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
                "result": {
                    "path": str((task_dir / "result.json").relative_to(output_dir))
                },
                "run_record": {
                    "path": str(
                        (task_dir / "run_record.json").relative_to(output_dir)
                    )
                },
            }
        )
    psi4, qcelemental, _atomic_input, _atomic_result, qcengine = _require_qm_stack()
    manifest = {
        "schema": "nadoc.photoproduct-distributed-hessian-plan.v1",
        "status": "prepared_not_run",
        "gate_effect": "none",
        "job_kind": "fixed_geometry_hessian",
        "product_id": job["product_id"],
        "model_id": job["model_id"],
        "conformer": job["conformer"],
        "fixed_geometry_hessian_job": {
            "path": str((job_dir / "job_manifest.json").resolve()),
            "sha256": _sha256(job_dir / "job_manifest.json"),
            "input_sha256": _sha256(job_dir / "input.dat"),
        },
        "reviewed_coupled_conformer_plan": job["coupled_conformer_plan"],
        "protocol": {
            "job_key": "fixed_geometry_hessian",
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
        "atom_map": job["atom_map"],
        "task_count": len(task_records),
        "finite_difference": {
            "mode": plan.metameta["mode"],
            "stencil_size": plan.findifrec["stencil_size"],
            "step": plan.findifrec["step"],
            "molecular_point_group": molecule.schoenflies_symbol(),
            "center_gradient_retained": True,
        },
        "default_resources_per_task": {
            "threads": job["threads"],
            "memory_gib": job["memory_gib"],
        },
        "tasks": task_records,
        "interpretation": (
            "Tasks may run independently, but assembly must recreate and byte-compare "
            "each input. The result is an off-equilibrium force/Hessian target, not a "
            "harmonic-frequency or stationary-point assertion."
        ),
    }
    manifest_path = output_dir / "distributed_hessian_plan.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def assemble_distributed_fixed_geometry_hessian(
    *, job_dir: Path, plan_path: Path, output_path: Path
) -> dict[str, Any]:
    """Audit all task pairs and emit fixed-geometry gradient/Hessian artifacts."""

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite distributed response audit: {output_path}"
        )
    job, source_path, protocol_path = _validated_fixed_geometry_job(job_dir)
    distributed, root = _load_plan(plan_path)
    job_record = distributed.get("fixed_geometry_hessian_job") or {}
    if (
        distributed.get("job_kind") != "fixed_geometry_hessian"
        or job_record.get("sha256") != _sha256(job_dir / "job_manifest.json")
        or job_record.get("input_sha256") != _sha256(job_dir / "input.dat")
        or distributed.get("protocol", {}).get("job_key")
        != "fixed_geometry_hessian"
        or distributed.get("protocol", {}).get("sha256") != _sha256(protocol_path)
        or distributed.get("product_id") != job["product_id"]
        or distributed.get("model_id") != job["model_id"]
        or distributed.get("conformer") != job["conformer"]
        or distributed.get("atom_map") != job["atom_map"]
    ):
        raise ValueError("distributed response plan does not match the reviewed job")

    plan, _molecule = _build_fixed_geometry_plan(job, source_path, protocol_path)
    regenerated = list(plan.task_list.items())
    if len(regenerated) != len(distributed["tasks"]):
        raise ValueError("recreated fixed-geometry task count changed")
    psi4, qcelemental, AtomicInput, AtomicResult, qcengine = _require_qm_stack()
    local_versions = {
        "version": str(psi4.__version__),
        "qcengine_version": str(qcengine.__version__),
        "qcelemental_version": str(qcelemental.__version__),
    }
    if any(
        local_versions[key] != distributed["engine"].get(key)
        for key in local_versions
    ):
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
                (run.get("engine") or {}).get(key)
                != distributed["engine"].get(key)
                for key in local_versions
            )
        ):
            raise ValueError(
                f"distributed task run record is invalid: {task_record['id']}"
            )
        result = AtomicResult.model_validate_json(result_path.read_text())
        if (
            not result.success
            or result.input_data.model_dump(mode="json")
            != computer.plan().model_dump(mode="json")
        ):
            raise ValueError(
                f"distributed task result/input mismatch: {task_record['id']}"
            )
        versions.add(str(result.provenance.version))
        computer.result = _restore_qcengine_arrays(result)
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
        raise ValueError("distributed tasks used an inconsistent Psi4 version")

    assembled = plan.get_results()
    hessian = np.asarray(assembled.return_result, dtype=float)
    gradient_value = getattr(assembled.properties, "return_gradient", None)
    if gradient_value is None:
        gradient_value = (assembled.extras.get("qcvars") or {}).get("CURRENT GRADIENT")
    gradient = np.asarray(gradient_value, dtype=float).reshape(-1)
    dimension = 3 * int(job["atom_count"])
    if (
        gradient.shape != (dimension,)
        or hessian.shape != (dimension, dimension)
        or not np.isfinite(gradient).all()
        or not np.isfinite(hessian).all()
    ):
        raise ValueError("assembled fixed-geometry gradient/Hessian is malformed")
    symmetry_error = float(np.max(np.abs(hessian - hessian.T)))
    if symmetry_error > 1.0e-8:
        raise ValueError("assembled fixed-geometry Hessian exceeds symmetry tolerance")

    gradient_path = job_dir / "gradient_hartree_per_bohr.txt"
    hessian_path = job_dir / "hessian_hartree_per_bohr2.txt"
    summary_path = job_dir / "output.dat"
    run_path = job_dir / "run_manifest.json"
    assembled_result_path = job_dir / "distributed_qcschema_result.json"
    artifact_paths = (
        gradient_path,
        hessian_path,
        summary_path,
        run_path,
        assembled_result_path,
    )
    if any(path.exists() for path in artifact_paths):
        raise FileExistsError("refusing to overwrite assembled fixed-geometry artifacts")
    np.savetxt(gradient_path, gradient, fmt="%.16e")
    np.savetxt(hessian_path, hessian, fmt="%.16e")
    assembled_result_path.write_bytes(
        _canonical_json_bytes(assembled.model_dump(mode="json"))
    )
    summary_path.write_text(
        "\n".join(
            (
                "NADOC distributed Psi4 fixed-geometry response assembly",
                f"Psi4 version {next(iter(versions))}",
                f"Tasks {len(task_audits)}; method {job['method']}/{job['basis']}",
                f"Conformer {job['conformer']['id']} ({job['conformer']['partition']})",
                "Center gradient retained; no optimization or frequency analysis performed.",
                "All displaced-gradient results passed hash and identity audit.",
            )
        )
        + "\n"
    )
    outputs = {
        path.name: {
            "path": str(path.resolve()),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in (summary_path, gradient_path, hessian_path, assembled_result_path)
    }
    run_record = {
        "schema": "nadoc.photoproduct-qm-run.v1",
        "status": "completed_unreviewed",
        "gate_effect": "none",
        "job_manifest_sha256": _sha256(job_dir / "job_manifest.json"),
        "command": ["distributed-qcengine-psi4", "assemble-fixed-geometry"],
        "returncode": 0,
        "parsed": {
            "psi4_success_exit": True,
            "optimization_complete": None,
            "final_energy_hartree": float(assembled.properties.return_energy),
            "passed_execution_checks": True,
            "execution_mode": "hash-audited-distributed-fixed-geometry-response",
        },
        "outputs": outputs,
        "distributed_hessian_plan": {
            "path": str(plan_path.resolve()),
            "sha256": _sha256(plan_path),
        },
    }
    run_path.write_text(json.dumps(run_record, indent=2) + "\n")
    report = {
        "schema": "nadoc.photoproduct-distributed-fixed-hessian-audit.v1",
        "status": "assembled_unreviewed_response",
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": job["product_id"],
        "model_id": job["model_id"],
        "conformer_id": job["conformer"]["id"],
        "partition": job["conformer"]["partition"],
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
        "cartesian_gradient": {
            **outputs[gradient_path.name],
            "units": "hartree/bohr",
            "dimension": dimension,
        },
        "cartesian_hessian": {
            **outputs[hessian_path.name],
            "units": "hartree/bohr^2",
            "dimension": dimension,
            "maximum_symmetry_error": symmetry_error,
        },
        "fixed_geometry_job_run_manifest_sha256": _sha256(run_path),
        "interpretation": (
            "This is a hash-audited force/Hessian at the exact reviewed geometry. It "
            "does not assert a harmonic minimum, approve a parameter fit, or make a "
            "simulation-ready force field. The ordinary fixed-geometry audit remains "
            "required before target extraction."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
