"""Diagnose unresolved bonded-fit directions without fitting force-field values."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked_path(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} source record is missing")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path


def _matrix_diagnostics(
    matrix: np.ndarray,
    parameters: list[dict[str, Any]],
    *,
    relative_threshold: float,
) -> dict[str, Any]:
    """Return scale-explicit SVD/null-space evidence for one homogeneous block."""

    values = np.asarray(matrix, dtype=float)
    if (
        values.ndim != 2
        or values.shape[1] != len(parameters)
        or not np.all(np.isfinite(values))
        or not 0.0 < relative_threshold < 1.0
    ):
        raise ValueError("fit response matrix, parameter count, or threshold is invalid")
    # Full right singular vectors are required when a block has fewer rows than
    # parameters (the projected-gradient block is 3N by P). The omitted vectors in a
    # reduced SVD are real, exact parameter-space null directions.
    _left, singular_values, right = np.linalg.svd(values, full_matrices=True)
    largest = float(singular_values[0]) if len(singular_values) else 0.0
    smallest = (
        0.0
        if values.shape[1] > len(singular_values)
        else float(singular_values[-1])
    )
    cutoff = largest * relative_threshold
    rank = int(np.count_nonzero(singular_values > cutoff))
    nullity = len(parameters) - rank
    nullspace = right[rank:, :] if nullity else np.empty((0, len(parameters)))
    participation = (
        np.sum(nullspace**2, axis=0) if nullity else np.zeros(len(parameters))
    )
    column_norms = np.linalg.norm(values, axis=0)
    nonzero = column_norms > 0.0
    normalized = np.zeros_like(values)
    normalized[:, nonzero] = values[:, nonzero] / column_norms[nonzero]
    correlations = normalized.T @ normalized
    correlated_pairs = []
    for first in range(len(parameters)):
        for second in range(first + 1, len(parameters)):
            absolute = abs(float(correlations[first, second]))
            if absolute >= 0.999999:
                correlated_pairs.append(
                    {
                        "parameter_1": parameters[first]["name"],
                        "parameter_2": parameters[second]["name"],
                        "correlation": float(correlations[first, second]),
                    }
                )
    correlated_pairs.sort(key=lambda item: -abs(item["correlation"]))

    groups: dict[str, dict[str, Any]] = {}
    for index, parameter in enumerate(parameters):
        group_id = str(parameter.get("group_id") or "")
        category = str(parameter.get("category") or "")
        if not group_id or not category:
            raise ValueError("linear parameter map lacks group/category identity")
        group = groups.setdefault(
            group_id,
            {
                "group_id": group_id,
                "category": category,
                "parameter_count": 0,
                "nullspace_participation_sum": 0.0,
                "maximum_parameter_participation": 0.0,
                "zero_response_parameter_count": 0,
            },
        )
        if group["category"] != category:
            raise ValueError("one fit group appears in multiple parameter categories")
        score = float(participation[index])
        group["parameter_count"] += 1
        group["nullspace_participation_sum"] += score
        group["maximum_parameter_participation"] = max(
            group["maximum_parameter_participation"], score
        )
        group["zero_response_parameter_count"] += int(not nonzero[index])
    ranked_groups = sorted(
        groups.values(),
        key=lambda item: (
            -item["nullspace_participation_sum"],
            item["group_id"],
        ),
    )

    null_directions = []
    for vector_index in range(rank, len(parameters)):
        vector = right[vector_index]
        dominant = sorted(
            (
                {
                    "parameter": parameters[index]["name"],
                    "coefficient": float(value),
                    "group_id": parameters[index]["group_id"],
                }
                for index, value in enumerate(vector)
            ),
            key=lambda item: -abs(item["coefficient"]),
        )[:8]
        null_directions.append(
            {
                "singular_value": (
                    float(singular_values[vector_index])
                    if vector_index < len(singular_values)
                    else 0.0
                ),
                "dominant_parameters": dominant,
            }
        )
    return {
        "row_count": int(values.shape[0]),
        "column_count": int(values.shape[1]),
        "relative_rank_threshold": relative_threshold,
        "absolute_singular_value_cutoff": cutoff,
        "rank": rank,
        "nullity": nullity,
        "largest_singular_value": largest,
        "smallest_singular_value": smallest,
        "condition_number_if_full_rank": (
            largest / smallest
            if nullity == 0 and smallest > 0.0
            else None
        ),
        "zero_response_parameters": [
            parameters[index]["name"]
            for index, present in enumerate(nonzero)
            if not present
        ],
        "near_collinear_parameter_pairs": correlated_pairs[:100],
        "ranked_group_nullspace_participation": ranked_groups,
        "null_directions": null_directions[:20],
    }


def _fit_group_evidence(
    fit_plan: dict[str, Any], parameters: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Join linear groups to their reviewed target class without guessing scanability."""

    groups: dict[str, dict[str, Any]] = {}
    for item in fit_plan.get("uncovered_parameter_groups") or []:
        group_id = str(item.get("id") or "")
        category = str(item.get("category") or "")
        if not group_id or category not in {"angles", "dihedrals"}:
            raise ValueError("fit plan contains a malformed uncovered parameter group")
        target_classes = sorted(
            {
                str(occurrence["target_class"])
                for occurrence in item.get("occurrences") or []
                if occurrence.get("target_class")
            }
        )
        groups[group_id] = {
            "group_id": group_id,
            "category": category,
            "target_classes": target_classes,
            "fit_plan_requirement": item.get("additional_target_requirement"),
        }
    for item in fit_plan.get("stereochemical_impropers") or []:
        stereocenter = str(item.get("stereocenter") or "")
        if not stereocenter:
            raise ValueError("fit plan contains a malformed stereochemical improper")
        group_id = f"improper:{stereocenter}"
        groups[group_id] = {
            "group_id": group_id,
            "category": "impropers",
            "target_classes": ["stereochemistry_preserving_improper"],
            "fit_plan_requirement": "ring_puckering_and_inversion_barrier",
        }
    parameter_groups = {
        str(item.get("group_id") or ""): str(item.get("category") or "")
        for item in parameters
    }
    if "" in parameter_groups:
        raise ValueError("linear parameter map lacks fit-group identity")
    for group_id, category in parameter_groups.items():
        if group_id not in groups or groups[group_id]["category"] != category:
            raise ValueError(
                f"linear parameter group {group_id} is absent or mismatched in the fit plan"
            )
    if set(groups) != set(parameter_groups):
        raise ValueError("fit plan and linear parameter map contain different fit groups")
    return groups


def _additional_evidence_requirement(group: dict[str, Any]) -> str:
    category = group["category"]
    target_classes = set(group["target_classes"])
    if category == "angles":
        return (
            "additional stereochemistry-preserving conformer Hessians and independently "
            "chosen off-equilibrium angle distortions"
        )
    if category == "impropers":
        return (
            "stereochemistry-preserving ring-puckering distortions plus an inversion-barrier "
            "check that never crosses to a different registered product"
        )
    if category != "dihedrals":
        raise ValueError(f"unsupported fit category {category}")
    if target_classes == {"coupled_ring_response_no_independent_scan"}:
        return (
            "stereochemistry-preserving coupled ring-pucker conformers with Cartesian "
            "Hessians; do not independently scan a cyclic central bond"
        )
    if target_classes == {"relaxed_torsion_scan_candidate"}:
        return (
            "reviewed relaxed QM torsion surfaces with independent conformers reserved "
            "for validation"
        )
    if target_classes == {"conjugated_or_multiple_bond_no_free_rotation_scan"}:
        return (
            "reviewed coupled conformers and Cartesian Hessians; do not treat the central "
            "bond as a freely rotatable torsion"
        )
    return (
        "mixed dihedral target classes require an explicit per-occurrence review and "
        "stereochemistry-preserving coupled conformer/Hessian evidence"
    )


def audit_openmm_fit_identifiability(
    *,
    response_manifest_path: Path,
    fit_plan_path: Path,
    output_path: Path,
    relative_threshold: float = 1.0e-8,
) -> dict[str, Any]:
    """Write a gate-neutral diagnosis of what one QM minimum cannot determine."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite identifiability audit: {output_path}")
    response = json.loads(response_manifest_path.read_text())
    if (
        response.get("schema") != "nadoc.photoproduct-openmm-linear-response.v1"
        or response.get("status") != "candidate_response_unfitted_not_releasable"
        or response.get("simulation_ready") is not False
        or response.get("gate_effect") != "none"
    ):
        raise ValueError("a gate-neutral unfitted OpenMM response is required")
    arrays_path = _checked_path(
        (response.get("outputs") or {}).get("linear_response_arrays"),
        "linear response arrays",
    )
    parameter_map_path = _checked_path(
        (response.get("sources") or {}).get("linear_parameter_map"),
        "linear parameter map",
    )
    fit_basis_path = _checked_path(
        (response.get("sources") or {}).get("fit_basis_manifest"),
        "fit basis manifest",
    )
    fit_basis = json.loads(fit_basis_path.read_text())
    linked_fit_plan = (fit_basis.get("sources") or {}).get("fit_plan")
    if (
        fit_basis.get("schema") != "nadoc.photoproduct-openmm-linear-fit-basis.v1"
        or not isinstance(linked_fit_plan, dict)
        or linked_fit_plan.get("sha256") != _sha256(fit_plan_path)
    ):
        raise ValueError("response fit basis does not hash-link the supplied fit plan")
    fit_plan = json.loads(fit_plan_path.read_text())
    if (
        fit_plan.get("schema") != "nadoc.photoproduct-bonded-fit-plan.v1"
        or fit_plan.get("status") != "candidate_plan_unassigned_not_releasable"
        or any(
            fit_plan.get(key) != response.get(key)
            for key in ("product_id", "model_id", "hypothesis_id")
        )
    ):
        raise ValueError("bonded fit plan is incompatible with the response")
    parameters = json.loads(parameter_map_path.read_text())
    if (
        not isinstance(parameters, list)
        or len(parameters) != response.get("parameter_count")
        or len({item.get("name") for item in parameters}) != len(parameters)
    ):
        raise ValueError("linear parameter map is malformed or differs from the response")
    fit_groups = _fit_group_evidence(fit_plan, parameters)
    with np.load(arrays_path, allow_pickle=False) as arrays:
        try:
            projected_gradient = np.asarray(
                arrays["projected_design_gradient"], dtype=float
            )
            projected_hessian = np.asarray(
                arrays["projected_design_hessian_upper"], dtype=float
            )
        except KeyError as exc:
            raise ValueError(f"linear response arrays lack {exc.args[0]}") from exc
    gradient = _matrix_diagnostics(
        projected_gradient,
        parameters,
        relative_threshold=relative_threshold,
    )
    hessian = _matrix_diagnostics(
        projected_hessian,
        parameters,
        relative_threshold=relative_threshold,
    )
    block_scales = {
        "projected_gradient": gradient["largest_singular_value"],
        "projected_hessian": hessian["largest_singular_value"],
    }
    if any(value <= 0.0 for value in block_scales.values()):
        raise ValueError("gradient or Hessian response block has no nonzero response")
    joint = _matrix_diagnostics(
        np.vstack(
            (
                projected_gradient / block_scales["projected_gradient"],
                projected_hessian / block_scales["projected_hessian"],
            )
        ),
        parameters,
        relative_threshold=relative_threshold,
    )
    unresolved_groups = []
    for diagnostic in joint["ranked_group_nullspace_participation"]:
        if diagnostic["nullspace_participation_sum"] <= 1.0e-10:
            continue
        group = fit_groups[diagnostic["group_id"]]
        unresolved_groups.append(
            {
                **group,
                "nullspace_participation_sum": diagnostic[
                    "nullspace_participation_sum"
                ],
                "maximum_parameter_participation": diagnostic[
                    "maximum_parameter_participation"
                ],
                "additional_evidence_required": _additional_evidence_requirement(group),
            }
        )
    unresolved_categories = sorted({item["category"] for item in unresolved_groups})
    additional_evidence = list(
        dict.fromkeys(item["additional_evidence_required"] for item in unresolved_groups)
    )
    passed = joint["nullity"] == 0
    report = {
        "schema": "nadoc.photoproduct-fit-identifiability-audit.v2",
        "status": (
            "full_rank_diagnostic_only_validation_still_required"
            if passed
            else "underdetermined_additional_qm_evidence_required"
        ),
        "passed_full_rank_diagnostic": passed,
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": response["product_id"],
        "model_id": response["model_id"],
        "hypothesis_id": response["hypothesis_id"],
        "parameter_count": len(parameters),
        "projected_gradient_block": gradient,
        "projected_hessian_block": hessian,
        "joint_normalized_diagnostic_block": {
            **joint,
            "normalization": (
                "gradient and Hessian blocks were each divided by their own largest "
                "singular value before vertical stacking; this is an identifiability "
                "diagnostic, not an objective-function weighting"
            ),
            "block_divisors": block_scales,
        },
        "unresolved_categories": unresolved_categories,
        "unresolved_group_requirements": unresolved_groups,
        "additional_evidence_required": additional_evidence,
        "sources": {
            "linear_response_manifest": {
                "path": str(response_manifest_path.resolve()),
                "sha256": _sha256(response_manifest_path),
            },
            "linear_response_arrays": {
                "path": str(arrays_path.resolve()),
                "sha256": _sha256(arrays_path),
            },
            "linear_parameter_map": {
                "path": str(parameter_map_path.resolve()),
                "sha256": _sha256(parameter_map_path),
            },
            "fit_basis_manifest": {
                "path": str(fit_basis_path.resolve()),
                "sha256": _sha256(fit_basis_path),
            },
            "bonded_fit_plan": {
                "path": str(fit_plan_path.resolve()),
                "sha256": _sha256(fit_plan_path),
            },
        },
        "interpretation": (
            "This audit identifies parameter combinations that the current response cannot "
            "separate. It neither chooses a reduced basis nor fits a force constant. Full "
            "rank alone would not establish transferability, physical bounds, or validation."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
