"""Fit a gate-neutral bonded smoke candidate from one full d(TpT) response.

The deterministic row holdout is a numerical regularization selector, not an
independent conformer test. The output can feed candidate CHARMM/NAMD assembly but
cannot pass a force-field release gate.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from backend.parameterization.photoproduct_response_campaign import _load_response
from backend.parameterization.photoproduct_response_fit import (
    transform_linear_coefficients_to_charmm,
)


POLICY_PATH = (
    Path(__file__).parents[1]
    / "data/forcefield/photoproduct_boundary_bonded_fit_policy.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _checked(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} source record is missing")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path.resolve()


def _rule_key(parameter: dict[str, Any]) -> str:
    basis = str(parameter.get("basis") or "")
    return "cosine_dihedral" if basis.startswith("cos(") else basis


def _block_metrics(
    design: np.ndarray,
    target: np.ndarray,
    coefficients: np.ndarray,
    mask: np.ndarray,
) -> dict[str, float | int]:
    residual = design[mask] @ coefficients - target[mask]
    return {
        "row_count": int(np.sum(mask)),
        "rmse": float(np.sqrt(np.mean(residual**2))),
        "maximum_absolute_error": float(np.max(np.abs(residual))),
        "target_rms": float(np.sqrt(np.mean(target[mask] ** 2))),
    }


def fit_boundary_bonded_response(
    *,
    response_manifest_path: Path,
    fit_plan_path: Path,
    output_dir: Path,
    policy_path: Path = POLICY_PATH,
) -> dict[str, Any]:
    """Select a physical bounded-ridge row for one ordered product."""

    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite boundary bonded fit: {output_dir}")
    policy = json.loads(policy_path.read_text())
    fit_plan = json.loads(fit_plan_path.read_text())
    dataset = _load_response(response_manifest_path)
    response = dataset["response"]
    if (
        policy.get("schema") != "nadoc.photoproduct-boundary-bonded-fit-policy.v1"
        or policy.get("version") != "1.0.0"
        or policy.get("status") != "workflow_policy"
        or fit_plan.get("schema") != "nadoc.photoproduct-bonded-fit-plan.v1"
        or fit_plan.get("status") != "candidate_plan_unassigned_not_releasable"
        or any(
            response.get(key) != fit_plan.get(key)
            for key in ("product_id", "model_id", "hypothesis_id")
        )
        or response.get("atom_count") != 63
        or response.get("cartesian_dimension") != 189
    ):
        raise ValueError("full-boundary response, fit plan, or policy identity differs")
    basis_path = _checked(
        (response.get("sources") or {}).get("fit_basis_manifest"),
        "linear fit-basis manifest",
    )
    basis = json.loads(basis_path.read_text())
    if (
        ((basis.get("sources") or {}).get("fit_plan") or {}).get("sha256")
        != _sha256(fit_plan_path)
        or basis.get("improper_equilibrium_mode") != "fixed_qm_reference"
        or basis.get("angle_urey_bradley_mode") != "omit"
    ):
        raise ValueError("response basis is not the corrected full-boundary representation")
    parameters = dataset["parameters"]
    representation = policy["representation"]
    if (
        sorted(
            {
                item["periodicity"]
                for item in parameters
                if item.get("category") == "dihedrals"
            }
        )
        != representation["torsion_periodicities"]
        or any(item.get("basis") in {"r13^2", "r13"} for item in parameters)
    ):
        raise ValueError("linear response periodicities or Urey-Bradley mode differ")

    arrays = dataset["arrays"]
    gradient_design = arrays["projected_design_gradient"]
    gradient_target = arrays["projected_residual_gradient"]
    hessian_design = arrays["projected_design_hessian_upper"]
    hessian_target = arrays["projected_residual_hessian_upper"]
    gradient_holdout = np.arange(len(gradient_target)) % 5 == 0
    hessian_holdout = np.arange(len(hessian_target)) % 5 == 0
    if not (
        0.19 <= float(np.mean(gradient_holdout)) <= 0.21
        and 0.19 <= float(np.mean(hessian_holdout)) <= 0.21
    ):
        raise ValueError("deterministic response row holdout is not 20 percent")
    minimum_rms = float(policy["objective"]["minimum_target_rms"])
    gradient_scale = max(
        float(np.sqrt(np.mean(gradient_target[~gradient_holdout] ** 2))), minimum_rms
    )
    hessian_scale = max(
        float(np.sqrt(np.mean(hessian_target[~hessian_holdout] ** 2))), minimum_rms
    )
    design = np.vstack(
        (
            gradient_design[~gradient_holdout]
            / gradient_scale
            / math.sqrt(int(np.sum(~gradient_holdout))),
            hessian_design[~hessian_holdout]
            / hessian_scale
            / math.sqrt(int(np.sum(~hessian_holdout))),
        )
    )
    target = np.concatenate(
        (
            gradient_target[~gradient_holdout]
            / gradient_scale
            / math.sqrt(int(np.sum(~gradient_holdout))),
            hessian_target[~hessian_holdout]
            / hessian_scale
            / math.sqrt(int(np.sum(~hessian_holdout))),
        )
    )
    rules = policy["coefficient_rules"]
    try:
        parameter_rules = [rules[_rule_key(item)] for item in parameters]
    except KeyError as exc:
        raise ValueError(f"no coefficient policy for parameter basis {exc.args[0]!r}") from exc
    scales = np.asarray([item["scale"] for item in parameter_rules], dtype=float)
    lower = np.asarray([item["lower_bound"] for item in parameter_rules], dtype=float)
    upper = np.asarray([item["upper_bound"] for item in parameter_rules], dtype=float)
    if (
        np.any(~np.isfinite(scales))
        or np.any(scales <= 0.0)
        or np.any(lower >= upper)
        or np.any(lower > 0.0)
        or np.any(upper < 0.0)
    ):
        raise ValueError("boundary bonded coefficient scale/bounds are nonphysical")

    try:
        import scipy
        from scipy.optimize import lsq_linear
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("SciPy is required for boundary bonded fitting") from exc

    scaled_design = design * scales[None, :]
    candidates = []
    coefficient_rows = []
    physical_rows = []
    for ridge_lambda in policy["objective"]["ridge_lambdas"]:
        ridge = float(ridge_lambda)
        if ridge > 0.0:
            augmented_design = np.vstack(
                (scaled_design, math.sqrt(ridge) * np.eye(len(parameters)))
            )
            augmented_target = np.concatenate((target, np.zeros(len(parameters))))
        else:
            augmented_design, augmented_target = scaled_design, target
        fit = lsq_linear(
            augmented_design,
            augmented_target,
            bounds=(lower / scales, upper / scales),
            method="trf",
            tol=1e-12,
            lsmr_tol=1e-12,
            max_iter=2000,
        )
        if not fit.success or not np.all(np.isfinite(fit.x)):
            raise ValueError(f"bounded ridge fit failed for lambda {ridge}: {fit.message}")
        coefficients = fit.x * scales
        parameter_rows = [
            {
                **parameter,
                "coefficient": float(value),
                "scale": float(scale),
                "lower_bound": float(minimum),
                "upper_bound": float(maximum),
            }
            for parameter, value, scale, minimum, maximum in zip(
                parameters, coefficients, scales, lower, upper, strict=True
            )
        ]
        physical = True
        stereo = True
        transformed = None
        try:
            transformed = transform_linear_coefficients_to_charmm(parameter_rows)
        except ValueError:
            physical = False
        if transformed is not None:
            expected = {
                item["group_id"]: item.get("expected_signed_volume")
                for item in parameter_rows
                if item.get("category") == "impropers"
            }
            stereo = bool(expected) and all(
                expected.get(item["group_id"]) in {"positive", "negative"}
                and (
                    (expected[item["group_id"]] == "positive" and item["psi0_degrees"] > 0)
                    or (expected[item["group_id"]] == "negative" and item["psi0_degrees"] < 0)
                )
                for item in transformed["impropers"]
            )
        training = {
            "gradient": _block_metrics(
                gradient_design, gradient_target, coefficients, ~gradient_holdout
            ),
            "hessian": _block_metrics(
                hessian_design, hessian_target, coefficients, ~hessian_holdout
            ),
        }
        held_out = {
            "gradient": _block_metrics(
                gradient_design, gradient_target, coefficients, gradient_holdout
            ),
            "hessian": _block_metrics(
                hessian_design, hessian_target, coefficients, hessian_holdout
            ),
        }
        held_gradient_rms = max(float(held_out["gradient"]["target_rms"]), minimum_rms)
        held_hessian_rms = max(float(held_out["hessian"]["target_rms"]), minimum_rms)
        score = (
            float(held_out["gradient"]["rmse"]) / held_gradient_rms
        ) ** 2 + (
            float(held_out["hessian"]["rmse"]) / held_hessian_rms
        ) ** 2
        record = {
            "ridge_lambda": ridge,
            "solver_status": int(fit.status),
            "solver_message": str(fit.message),
            "iterations": int(fit.nit or 0),
            "active_bound_count": int(np.count_nonzero(fit.active_mask)),
            "coefficient_l2_scaled": float(np.linalg.norm(fit.x)),
            "physical_charmm_transform": physical,
            "stereochemical_basin": stereo,
            "training": training,
            "held_out": held_out,
            "held_out_score": score,
        }
        candidates.append(record)
        coefficient_rows.append(coefficients)
        physical_rows.append((record, parameter_rows, transformed))

    eligible = [item for item in physical_rows if item[0]["physical_charmm_transform"] and item[0]["stereochemical_basin"]]
    if not eligible:
        raise ValueError("no bounded-ridge row has a physical stereochemistry-preserving CHARMM transform")
    best_score = min(item[0]["held_out_score"] for item in eligible)
    window = best_score * (
        1.0 + float(policy["candidate_selection"]["near_best_relative_window"])
    )
    finalists = [item for item in eligible if item[0]["held_out_score"] <= window + 1e-15]
    selected_record, selected_parameters, transformed = min(
        finalists,
        key=lambda item: (
            item[0]["active_bound_count"],
            item[0]["coefficient_l2_scaled"],
            -item[0]["ridge_lambda"],
            item[0]["held_out_score"],
        ),
    )
    assert transformed is not None

    output_dir.mkdir(parents=True)
    coefficients_path = output_dir / "candidate_coefficients.npz"
    np.savez_compressed(
        coefficients_path,
        ridge_lambdas=np.asarray(policy["objective"]["ridge_lambdas"], dtype=float),
        coefficients=np.asarray(coefficient_rows),
        scales=scales,
        lower_bounds=lower,
        upper_bounds=upper,
    )
    evaluation = {
        "schema": "nadoc.photoproduct-boundary-bonded-fit-evaluation.v1",
        "status": "candidate_rows_evaluated_and_selected_for_smoke",
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": response["product_id"],
        "model_id": response["model_id"],
        "hypothesis_id": response["hypothesis_id"],
        "parameter_count": len(parameters),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "selected_ridge_lambda": selected_record["ridge_lambda"],
        "software": {"numpy": np.__version__, "scipy": scipy.__version__},
        "partition": policy["response_partition"],
        "sources": {
            "response": _source(response_manifest_path),
            "fit_plan": _source(fit_plan_path),
            "policy": _source(policy_path),
        },
        "outputs": {"candidate_coefficients": _source(coefficients_path)},
    }
    evaluation_path = output_dir / "evaluation.json"
    evaluation_path.write_text(json.dumps(evaluation, indent=2) + "\n")
    selected = {
        "schema": "nadoc.photoproduct-selected-response-fit-candidate.v1",
        "status": "quantitatively_selected_candidate_requires_charmm_mapping_and_validation",
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": response["product_id"],
        "model_id": response["model_id"],
        "hypothesis_id": response["hypothesis_id"],
        "ridge_lambda": selected_record["ridge_lambda"],
        "selection_checks": {
            "physical_charmm_transform": {"passed": True},
            "stereochemical_basin": {"passed": True},
            "deterministic_row_holdout": {"passed": True},
        },
        "decision_authority": {
            "kind": "automated_quantitative_boundary_row_holdout_policy",
            "policy_source": _source(policy_path),
            "releases_parameters": False,
        },
        "training_metrics": selected_record["training"],
        "validation_metrics": selected_record["held_out"],
        "parameters": selected_parameters,
        "sources": {
            "boundary_fit_evaluation": _source(evaluation_path),
            "candidate_coefficients": _source(coefficients_path),
            "response": _source(response_manifest_path),
            "fit_plan": _source(fit_plan_path),
            "quantitative_selection_policy": _source(policy_path),
        },
        "release_blockers": policy["authorization"]["does_not_authorize"],
    }
    selected_path = output_dir / "selected_response_fit.json"
    selected_path.write_text(json.dumps(selected, indent=2) + "\n")
    transform = {
        "schema": "nadoc.photoproduct-charmm-bonded-transform-candidate.v1",
        "status": "algebraically_transformed_requires_term_mapping_and_validation",
        "simulation_ready": False,
        "gate_effect": "none",
        "hypothesis_id": response["hypothesis_id"],
        "ridge_lambda": selected_record["ridge_lambda"],
        "bonded_terms": transformed,
        "selection_authority": "automated_quantitative_boundary_row_holdout_policy",
        "sources": {"selected_response_fit_candidate": _source(selected_path)},
        "release_blockers": [
            "deterministic rows from one minimum are not independent conformers",
            "MM-minimum, DNA-context, psfgen, and NAMD validation remain incomplete",
        ],
        "interpretation": (
            "Exact algebraic transformation of a full d(TpT) response-row holdout fit; "
            "eligible for fail-closed engine smoke only, never force-field release."
        ),
    }
    transform_path = output_dir / "charmm_bonded_transform.json"
    transform_path.write_text(json.dumps(transform, indent=2) + "\n")
    report = {
        "schema": "nadoc.photoproduct-boundary-bonded-fit.v1",
        "status": "physical_candidate_selected_for_engine_smoke",
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": response["product_id"],
        "model_id": response["model_id"],
        "hypothesis_id": response["hypothesis_id"],
        "selected_ridge_lambda": selected_record["ridge_lambda"],
        "selected_held_out_score": selected_record["held_out_score"],
        "outputs": {
            "evaluation": _source(evaluation_path),
            "selected_response_fit": _source(selected_path),
            "charmm_bonded_transform": _source(transform_path),
        },
        "release_blockers": selected["release_blockers"],
    }
    report_path = output_dir / "boundary_bonded_fit.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
