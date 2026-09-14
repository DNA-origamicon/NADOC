"""Assemble independent photoproduct response datasets without fitting parameters."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from backend.parameterization.photoproduct_fit_identifiability import (
    _checked_path,
    _matrix_diagnostics,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_response(path: Path) -> dict[str, Any]:
    response = json.loads(path.read_text())
    if (
        response.get("schema") != "nadoc.photoproduct-openmm-linear-response.v1"
        or response.get("status") != "candidate_response_unfitted_not_releasable"
        or response.get("simulation_ready") is not False
        or response.get("gate_effect") != "none"
    ):
        raise ValueError(f"{path}: a gate-neutral unfitted OpenMM response is required")

    arrays_path = _checked_path(
        (response.get("outputs") or {}).get("linear_response_arrays"),
        f"{path} linear response arrays",
    )
    parameter_map_path = _checked_path(
        (response.get("sources") or {}).get("linear_parameter_map"),
        f"{path} linear parameter map",
    )
    stable_map_path = _checked_path(
        (response.get("sources") or {}).get("stable_atom_map"),
        f"{path} stable atom map",
    )
    hessian_source = (response.get("sources") or {}).get("hessian_targets")
    hessian_targets_path = _checked_path(
        hessian_source, f"{path} Hessian targets"
    )
    hessian_targets = json.loads(hessian_targets_path.read_text())
    target_schema = hessian_targets.get("schema")
    if target_schema == "nadoc.photoproduct-hessian-target-bundle.v1":
        if (
            hessian_targets.get("frequency_evidence_status")
            not in {"passed_harmonic_minimum", "passed_candidate_harmonic_minimum"}
            or hessian_targets.get("gate_effect") != "none"
        ):
            raise ValueError(f"{path}: minimum Hessian target is not passed evidence")
        reviewed_partition = None
    elif target_schema == "nadoc.photoproduct-hessian-target-bundle.v2":
        if (
            hessian_targets.get("status")
            != "candidate_off_equilibrium_response_evidence"
            or hessian_targets.get("simulation_ready") is not False
            or hessian_targets.get("gate_effect") != "none"
            or hessian_targets.get("target_kind")
            != "reviewed_off_equilibrium_conformer"
            or hessian_targets.get("partition") not in {"training", "validation"}
        ):
            raise ValueError(
                f"{path}: off-equilibrium Hessian target lacks a reviewed partition"
            )
        reviewed_partition = hessian_targets["partition"]
    else:
        raise ValueError(f"{path}: unsupported Hessian target schema")
    if any(
        hessian_targets.get(key) != response.get(key)
        for key in ("product_id", "model_id")
    ):
        raise ValueError(f"{path}: response and Hessian target identities differ")

    parameters = json.loads(parameter_map_path.read_text())
    parameter_count = response.get("parameter_count")
    if (
        not isinstance(parameters, list)
        or len(parameters) != parameter_count
        or len({item.get("name") for item in parameters}) != len(parameters)
    ):
        raise ValueError(f"{path}: linear parameter map is malformed")

    required_arrays = (
        "projected_design_gradient",
        "projected_residual_gradient",
        "projected_design_hessian_upper",
        "projected_residual_hessian_upper",
    )
    with np.load(arrays_path, allow_pickle=False) as archive:
        try:
            arrays = {
                name: np.asarray(archive[name], dtype=float) for name in required_arrays
            }
        except KeyError as exc:
            raise ValueError(f"{path}: linear response arrays lack {exc.args[0]}") from exc

    gradient = arrays["projected_design_gradient"]
    gradient_target = arrays["projected_residual_gradient"]
    hessian = arrays["projected_design_hessian_upper"]
    hessian_target = arrays["projected_residual_hessian_upper"]
    if (
        gradient.ndim != 2
        or hessian.ndim != 2
        or gradient.shape[1] != parameter_count
        or hessian.shape[1] != parameter_count
        or gradient_target.shape != (gradient.shape[0],)
        or hessian_target.shape != (hessian.shape[0],)
        or any(not np.all(np.isfinite(values)) for values in arrays.values())
    ):
        raise ValueError(f"{path}: projected response arrays have invalid shapes or values")

    source_hash = str(hessian_source.get("sha256") or "")
    dataset_identity = (
        str(response.get("product_id") or ""),
        str(response.get("model_id") or ""),
        source_hash,
    )
    if not all(dataset_identity) or not response.get("hypothesis_id"):
        raise ValueError(f"{path}: response dataset identity is incomplete")
    return {
        "manifest_path": path.resolve(),
        "manifest_sha256": _sha256(path),
        "response": response,
        "arrays_path": arrays_path.resolve(),
        "arrays_sha256": _sha256(arrays_path),
        "parameter_map_path": parameter_map_path.resolve(),
        "parameter_map_sha256": _sha256(parameter_map_path),
        "stable_map_path": stable_map_path.resolve(),
        "stable_map_sha256": _sha256(stable_map_path),
        "hessian_targets_path": hessian_targets_path.resolve(),
        "hessian_targets_sha256": source_hash,
        "reviewed_partition": reviewed_partition,
        "parameters": parameters,
        "dataset_identity": dataset_identity,
        "arrays": arrays,
    }


def _source_record(dataset: dict[str, Any], *, partition: str) -> dict[str, Any]:
    response = dataset["response"]
    product_id, model_id, hessian_hash = dataset["dataset_identity"]
    return {
        "dataset_id": f"{product_id}:{model_id}:{hessian_hash[:16]}",
        "partition": partition,
        "product_id": product_id,
        "model_id": model_id,
        "hypothesis_id": response["hypothesis_id"],
        "reviewed_partition": dataset["reviewed_partition"],
        "response_manifest": {
            "path": str(dataset["manifest_path"]),
            "sha256": dataset["manifest_sha256"],
        },
        "linear_response_arrays": {
            "path": str(dataset["arrays_path"]),
            "sha256": dataset["arrays_sha256"],
        },
        "hessian_targets": {
            "path": str(dataset["hessian_targets_path"]),
            "sha256": dataset["hessian_targets_sha256"],
        },
    }


def _largest_singular_value(matrix: np.ndarray) -> float:
    singular_values = np.linalg.svd(matrix, compute_uv=False)
    return float(singular_values[0]) if len(singular_values) else 0.0


def _diagnostic_blocks(
    datasets: Sequence[dict[str, Any]],
    parameters: list[dict[str, Any]],
    *,
    relative_threshold: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized_gradient: list[np.ndarray] = []
    normalized_hessian: list[np.ndarray] = []
    progression: list[dict[str, Any]] = []
    previous_rank = 0
    for dataset in datasets:
        gradient = dataset["arrays"]["projected_design_gradient"]
        hessian = dataset["arrays"]["projected_design_hessian_upper"]
        gradient_scale = _largest_singular_value(gradient)
        hessian_scale = _largest_singular_value(hessian)
        if gradient_scale <= 0.0 or hessian_scale <= 0.0:
            raise ValueError("a response dataset has an all-zero gradient or Hessian block")
        normalized_gradient.append(gradient / gradient_scale)
        normalized_hessian.append(hessian / hessian_scale)
        joint = np.vstack((*normalized_gradient, *normalized_hessian))
        diagnostic = _matrix_diagnostics(
            joint,
            parameters,
            relative_threshold=relative_threshold,
        )
        progression.append(
            {
                "dataset_id": _source_record(dataset, partition="training")[
                    "dataset_id"
                ],
                "gradient_divisor": gradient_scale,
                "hessian_divisor": hessian_scale,
                "cumulative_rank": diagnostic["rank"],
                "rank_gain": diagnostic["rank"] - previous_rank,
                "cumulative_nullity": diagnostic["nullity"],
            }
        )
        previous_rank = diagnostic["rank"]

    gradient = _matrix_diagnostics(
        np.vstack(normalized_gradient),
        parameters,
        relative_threshold=relative_threshold,
    )
    hessian = _matrix_diagnostics(
        np.vstack(normalized_hessian),
        parameters,
        relative_threshold=relative_threshold,
    )
    joint = _matrix_diagnostics(
        np.vstack((*normalized_gradient, *normalized_hessian)),
        parameters,
        relative_threshold=relative_threshold,
    )
    return (
        {
            "projected_gradient_block": gradient,
            "projected_hessian_block": hessian,
            "joint_normalized_diagnostic_block": joint,
            "normalization": (
                "Each dataset's projected gradient and projected Hessian design block was "
                "divided by its own largest singular value before stacking. This is an "
                "identifiability diagnostic, not a fit-objective weighting."
            ),
        },
        progression,
    )


def build_openmm_response_campaign(
    *,
    training_response_paths: Sequence[Path],
    validation_response_paths: Sequence[Path],
    output_dir: Path,
    relative_threshold: float = 1.0e-8,
) -> dict[str, Any]:
    """Build a disjoint, hash-linked training/holdout response campaign."""

    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite response campaign: {output_dir}")
    if not training_response_paths:
        raise ValueError("at least one training response is required")
    if not validation_response_paths:
        raise ValueError("at least one independent validation response is required")
    if not 0.0 < relative_threshold < 1.0:
        raise ValueError("relative threshold must be between zero and one")

    training = [_load_response(Path(path)) for path in training_response_paths]
    validation = [_load_response(Path(path)) for path in validation_response_paths]
    for expected_partition, partition_datasets in (
        ("training", training),
        ("validation", validation),
    ):
        for dataset in partition_datasets:
            reviewed_partition = dataset["reviewed_partition"]
            if (
                reviewed_partition is not None
                and reviewed_partition != expected_partition
            ):
                raise ValueError(
                    "reviewed conformer partition differs from its requested campaign "
                    f"partition: {reviewed_partition} != {expected_partition}"
                )
    datasets = [*training, *validation]
    manifest_hashes = [item["manifest_sha256"] for item in datasets]
    identities = [item["dataset_identity"] for item in datasets]
    if len(set(manifest_hashes)) != len(manifest_hashes):
        raise ValueError("training and validation response manifests must be disjoint")
    if len(set(identities)) != len(identities):
        raise ValueError("training and validation dataset identities must be unique")

    reference = datasets[0]
    for dataset in datasets[1:]:
        if dataset["parameter_map_sha256"] != reference["parameter_map_sha256"]:
            raise ValueError("all response datasets must use the exact same parameter map")
        if dataset["stable_map_sha256"] != reference["stable_map_sha256"]:
            raise ValueError("all response datasets must use the exact same stable atom map")
        if dataset["response"]["hypothesis_id"] != reference["response"]["hypothesis_id"]:
            raise ValueError("all response datasets must use the same parameter hypothesis")

    parameters = reference["parameters"]
    diagnostics, rank_progression = _diagnostic_blocks(
        training,
        parameters,
        relative_threshold=relative_threshold,
    )
    gradient_offsets = [0]
    hessian_offsets = [0]
    for dataset in training:
        gradient_offsets.append(
            gradient_offsets[-1]
            + dataset["arrays"]["projected_design_gradient"].shape[0]
        )
        hessian_offsets.append(
            hessian_offsets[-1]
            + dataset["arrays"]["projected_design_hessian_upper"].shape[0]
        )

    output_dir.mkdir(parents=True)
    arrays_path = output_dir / "training_response_arrays.npz"
    np.savez_compressed(
        arrays_path,
        projected_design_gradient=np.vstack(
            [item["arrays"]["projected_design_gradient"] for item in training]
        ),
        projected_residual_gradient=np.concatenate(
            [item["arrays"]["projected_residual_gradient"] for item in training]
        ),
        projected_design_hessian_upper=np.vstack(
            [item["arrays"]["projected_design_hessian_upper"] for item in training]
        ),
        projected_residual_hessian_upper=np.concatenate(
            [item["arrays"]["projected_residual_hessian_upper"] for item in training]
        ),
        gradient_row_offsets=np.asarray(gradient_offsets, dtype=np.int64),
        hessian_row_offsets=np.asarray(hessian_offsets, dtype=np.int64),
    )
    full_rank = diagnostics["joint_normalized_diagnostic_block"]["nullity"] == 0
    manifest = {
        "schema": "nadoc.photoproduct-openmm-response-campaign.v1",
        "status": (
            "training_design_full_rank_diagnostic_only"
            if full_rank
            else "training_design_underdetermined_additional_evidence_required"
        ),
        "simulation_ready": False,
        "gate_effect": "none",
        "hypothesis_id": reference["response"]["hypothesis_id"],
        "parameter_count": len(parameters),
        "training_dataset_count": len(training),
        "validation_dataset_count": len(validation),
        "partitions_disjoint": True,
        "training_identifiability": diagnostics,
        "training_rank_progression": rank_progression,
        "outputs": {
            "training_response_arrays": {
                "path": str(arrays_path.resolve()),
                "sha256": _sha256(arrays_path),
            }
        },
        "shared_sources": {
            "linear_parameter_map": {
                "path": str(reference["parameter_map_path"]),
                "sha256": reference["parameter_map_sha256"],
            },
            "stable_atom_map": {
                "path": str(reference["stable_map_path"]),
                "sha256": reference["stable_map_sha256"],
            },
        },
        "training_datasets": [
            _source_record(item, partition="training") for item in training
        ],
        "validation_datasets": [
            _source_record(item, partition="validation") for item in validation
        ],
        "release_blockers": [
            "no parameter coefficients have been fitted",
            "force-versus-Hessian objective weights require independent justification",
            "regularization, physical bounds, and torsion periodicities remain unreviewed",
            "the independent validation partition has not been evaluated against a fit",
            "full diagnostic rank would not establish transferability or simulation readiness",
        ],
        "interpretation": (
            "Only training responses are concatenated into the output arrays. Validation "
            "responses are hash-checked and reserved as a disjoint holdout partition. The "
            "rank progression measures complementary information without fitting values or "
            "advancing a force-field registry gate."
        ),
    }
    manifest_path = output_dir / "response_campaign_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
