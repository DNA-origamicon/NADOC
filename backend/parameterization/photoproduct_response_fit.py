"""Bounded, regularized response fitting with an immutable holdout boundary.

This module does not choose a force field.  It creates a human-reviewable objective
specification and evaluates every reviewed regularization candidate on the campaign's
untouched validation responses.  The resulting artifact remains gate-neutral and requires
independent scientific model selection.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from backend.parameterization.photoproduct_response_campaign import _load_response


RESPONSE_FIT_POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "forcefield"
    / "photoproduct_response_fit_policy.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _checked(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} record is missing")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path.resolve()


def _timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _campaign(
    path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    payload = json.loads(path.read_text())
    if (
        payload.get("schema") != "nadoc.photoproduct-openmm-response-campaign.v1"
        or payload.get("status")
        not in {
            "training_design_full_rank_diagnostic_only",
            "training_design_underdetermined_additional_evidence_required",
        }
        or payload.get("simulation_ready") is not False
        or payload.get("gate_effect") != "none"
        or payload.get("partitions_disjoint") is not True
    ):
        raise ValueError("a gate-neutral disjoint response campaign is required")
    training_records = payload.get("training_datasets") or []
    validation_records = payload.get("validation_datasets") or []
    if (
        not training_records
        or not validation_records
        or len(training_records) != payload.get("training_dataset_count")
        or len(validation_records) != payload.get("validation_dataset_count")
    ):
        raise ValueError("response campaign lacks training or validation datasets")

    def load(records: Sequence[dict[str, Any]], partition: str) -> list[dict[str, Any]]:
        datasets = []
        for record in records:
            if record.get("partition") != partition:
                raise ValueError("campaign dataset partition changed")
            manifest_path = _checked(
                record.get("response_manifest"), f"{partition} response manifest"
            )
            dataset = _load_response(manifest_path)
            if (
                record.get("dataset_id")
                != f"{dataset['dataset_identity'][0]}:{dataset['dataset_identity'][1]}:"
                f"{dataset['dataset_identity'][2][:16]}"
                or dataset["reviewed_partition"] not in {None, partition}
            ):
                raise ValueError(
                    "campaign dataset identity or reviewed partition changed"
                )
            datasets.append(dataset)
        return datasets

    training = load(training_records, "training")
    validation = load(validation_records, "validation")
    parameter_map_path = _checked(
        (payload.get("shared_sources") or {}).get("linear_parameter_map"),
        "campaign linear parameter map",
    )
    parameters = json.loads(parameter_map_path.read_text())
    if (
        not isinstance(parameters, list)
        or len(parameters) != payload.get("parameter_count")
        or [item.get("name") for item in parameters]
        != [item.get("name") for item in training[0]["parameters"]]
    ):
        raise ValueError("campaign parameter map is malformed or stale")
    for dataset in [*training, *validation]:
        if dataset["parameter_map_sha256"] != _sha256(parameter_map_path):
            raise ValueError("campaign response parameter map changed")

    combined_path = _checked(
        (payload.get("outputs") or {}).get("training_response_arrays"),
        "combined training arrays",
    )
    with np.load(combined_path, allow_pickle=False) as archive:
        expected = {
            "projected_design_gradient": np.vstack(
                [item["arrays"]["projected_design_gradient"] for item in training]
            ),
            "projected_residual_gradient": np.concatenate(
                [item["arrays"]["projected_residual_gradient"] for item in training]
            ),
            "projected_design_hessian_upper": np.vstack(
                [item["arrays"]["projected_design_hessian_upper"] for item in training]
            ),
            "projected_residual_hessian_upper": np.concatenate(
                [
                    item["arrays"]["projected_residual_hessian_upper"]
                    for item in training
                ]
            ),
        }
        if any(
            name not in archive or not np.array_equal(archive[name], values)
            for name, values in expected.items()
        ):
            raise ValueError("combined training arrays differ from source responses")
    payload["_parameter_map_path"] = str(parameter_map_path)
    payload["_parameters"] = parameters
    return payload, training, validation


def _fit_specification_template_payload(campaign_path: Path) -> dict[str, Any]:
    campaign, _training, _validation = _campaign(campaign_path)
    parameters = campaign.pop("_parameters")
    parameter_map_path = Path(campaign.pop("_parameter_map_path"))
    report = {
        "schema": "nadoc.photoproduct-response-fit-specification.v1",
        "status": "review_required",
        "simulation_ready": False,
        "gate_effect": "none",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_rationale": None,
        "campaign": _source(campaign_path),
        "parameter_map": _source(parameter_map_path),
        "objective": {
            "dataset_weighting": None,
            "gradient_weight": None,
            "hessian_weight": None,
            "ridge_lambdas": [],
        },
        "parameters": [
            {
                "name": item["name"],
                "group_id": item.get("group_id"),
                "category": item.get("category"),
                "basis": item.get("basis"),
                "coefficient_units": item.get("coefficient_units"),
                "periodicity": item.get("periodicity"),
                "reference_degrees": item.get("reference_degrees"),
                "expected_signed_volume": item.get("expected_signed_volume"),
                "ordered_atoms_candidate": item.get("ordered_atoms_candidate"),
                "occurrence_count": item.get("occurrence_count"),
                "scale": None,
                "lower_bound": None,
                "upper_bound": None,
            }
            for item in parameters
        ],
        "selection": None,
        "instructions": (
            "A qualified reviewer must choose raw_rows or equal_dataset_rms weighting; "
            "positive force/Hessian weights; a nonnegative ridge grid; and finite, "
            "physically justified scale and bounds for every coefficient. Keep selection "
            "null: this specification authorizes comparison, not force-field release."
        ),
    }
    return report


def build_response_fit_specification_template(
    *, campaign_path: Path, output_path: Path
) -> dict[str, Any]:
    """Create an unreviewed specification; no objective choice is inferred."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite fit specification: {output_path}")
    report = _fit_specification_template_payload(campaign_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def materialize_quantitative_response_fit_specification(
    *,
    campaign_path: Path,
    output_path: Path,
    policy_path: Path = RESPONSE_FIT_POLICY_PATH,
) -> dict[str, Any]:
    """Preregister a dimensionless bounded-ridge objective without human input."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite fit specification: {output_path}")
    policy = json.loads(policy_path.read_text())
    if (
        policy.get("schema") != "nadoc.photoproduct-response-fit-policy.v1"
        or policy.get("status") != "workflow_policy"
        or policy.get("policy")
        not in {
            "dimensionless-heldout-bounded-ridge-v1",
            "dimensionless-heldout-bounded-ridge-v2",
            "dimensionless-heldout-fixed-qm-improper-v3",
        }
    ):
        raise ValueError("unsupported quantitative response-fit policy")
    campaign, training, _validation = _campaign(campaign_path)
    campaign.pop("_parameter_map_path")
    campaign.pop("_parameters")
    report = _fit_specification_template_payload(campaign_path)
    minimum = float(policy["minimum_target_rms"])
    gradient_targets = np.concatenate(
        [item["arrays"]["projected_residual_gradient"] for item in training]
    )
    hessian_targets = np.concatenate(
        [item["arrays"]["projected_residual_hessian_upper"] for item in training]
    )
    gradient_rms = max(float(np.sqrt(np.mean(gradient_targets**2))), minimum)
    hessian_rms = max(float(np.sqrt(np.mean(hessian_targets**2))), minimum)
    report.update(
        {
            "status": "quantitatively_specified",
            "reviewed_by": None,
            "reviewed_at": None,
            "review_rationale": None,
            "quantitative_specification": {
                "schema": "nadoc.photoproduct-response-fit-quantitative-specification.v1",
                "status": "passed_preregistered_objective_screen",
                "policy": policy["policy"],
                "policy_source": _source(policy_path),
                "authorizes": "bounded_response_fit_evaluation_only",
                "releases_parameters": False,
                "training_target_rms": {
                    "gradient": gradient_rms,
                    "hessian": hessian_rms,
                },
            },
        }
    )
    report["objective"] = {
        "dataset_weighting": policy["dataset_weighting"],
        "gradient_weight": 1.0 / gradient_rms**2,
        "hessian_weight": 1.0 / hessian_rms**2,
        "ridge_lambdas": policy["ridge_lambdas"],
    }
    rules = policy["coefficient_rules"]
    for parameter in report["parameters"]:
        basis = str(parameter.get("basis") or "")
        rule_key = "cosine_dihedral" if basis.startswith("cos(") else basis
        rule = rules.get(rule_key)
        if not isinstance(rule, dict):
            raise ValueError(f"no quantitative coefficient rule for basis {basis!r}")
        parameter.update(
            {
                "scale": rule["scale"],
                "lower_bound": rule["lower_bound"],
                "upper_bound": rule["upper_bound"],
            }
        )
    report["instructions"] = (
        "Objective normalization, coefficient bounds, and ridge grid were fixed by the "
        "hash-pinned quantitative policy using training targets only. Evaluation may "
        "report untouched validation errors but cannot release parameters."
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def _reviewed_specification(
    path: Path,
    campaign_path: Path,
    parameters: Sequence[dict[str, Any]],
    training: Sequence[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray]:
    spec = json.loads(path.read_text())
    objective = spec.get("objective") or {}
    records = spec.get("parameters") or []
    common_invalid = (
        spec.get("schema") != "nadoc.photoproduct-response-fit-specification.v1"
        or spec.get("simulation_ready") is not False
        or spec.get("gate_effect") != "none"
        or spec.get("selection") is not None
        or objective.get("dataset_weighting") not in {"raw_rows", "equal_dataset_rms"}
    )
    automated = spec.get("status") == "quantitatively_specified"
    if spec.get("status") == "reviewed":
        authority_invalid = (
            not isinstance(spec.get("reviewed_by"), str)
            or not spec["reviewed_by"].strip()
            or not _timestamp(spec.get("reviewed_at"))
            or not isinstance(spec.get("review_rationale"), str)
            or len(spec["review_rationale"].strip()) < 20
        )
    elif automated:
        quantitative = spec.get("quantitative_specification") or {}
        policy_path = _checked(quantitative.get("policy_source"), "response-fit policy")
        policy = json.loads(policy_path.read_text())
        authority_invalid = (
            training is None
            or policy.get("schema") != "nadoc.photoproduct-response-fit-policy.v1"
            or quantitative.get("schema")
            != "nadoc.photoproduct-response-fit-quantitative-specification.v1"
            or quantitative.get("status") != "passed_preregistered_objective_screen"
            or quantitative.get("policy") != policy.get("policy")
            or quantitative.get("authorizes") != "bounded_response_fit_evaluation_only"
            or quantitative.get("releases_parameters") is not False
            or objective.get("dataset_weighting") != policy.get("dataset_weighting")
            or objective.get("ridge_lambdas") != policy.get("ridge_lambdas")
        )
        if not authority_invalid:
            minimum = float(policy["minimum_target_rms"])
            gradient = np.concatenate(
                [item["arrays"]["projected_residual_gradient"] for item in training]
            )
            hessian = np.concatenate(
                [
                    item["arrays"]["projected_residual_hessian_upper"]
                    for item in training
                ]
            )
            expected_rms = {
                "gradient": max(float(np.sqrt(np.mean(gradient**2))), minimum),
                "hessian": max(float(np.sqrt(np.mean(hessian**2))), minimum),
            }
            authority_invalid = quantitative.get(
                "training_target_rms"
            ) != expected_rms or not (
                math.isclose(
                    float(objective["gradient_weight"]),
                    1.0 / expected_rms["gradient"] ** 2,
                )
                and math.isclose(
                    float(objective["hessian_weight"]),
                    1.0 / expected_rms["hessian"] ** 2,
                )
            )
    else:
        authority_invalid = True
    if common_invalid or authority_invalid:
        raise ValueError(
            "fit specification lacks a complete non-selecting human review"
        )
    if (
        _checked(spec.get("campaign"), "fit-specification campaign")
        != campaign_path.resolve()
    ):
        raise ValueError("fit specification references a different campaign path")
    identity_fields = (
        "name",
        "group_id",
        "category",
        "basis",
        "coefficient_units",
        "periodicity",
        "reference_degrees",
        "expected_signed_volume",
        "ordered_atoms_candidate",
        "occurrence_count",
    )
    expected_identities = [
        tuple(item.get(field) for field in identity_fields) for item in parameters
    ]
    observed_identities = [
        tuple(item.get(field) for field in identity_fields) for item in records
    ]
    if observed_identities != expected_identities:
        raise ValueError(
            "fit specification parameter identity/order differs from campaign"
        )
    weights = [objective.get("gradient_weight"), objective.get("hessian_weight")]
    if any(
        not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0.0
        for value in weights
    ):
        raise ValueError(
            "gradient and Hessian objective weights must be finite and positive"
        )
    lambdas = objective.get("ridge_lambdas") or []
    if (
        not isinstance(lambdas, list)
        or len(lambdas) < 2
        or any(
            not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0.0
            for value in lambdas
        )
        or [float(value) for value in lambdas]
        != sorted(set(float(value) for value in lambdas))
    ):
        raise ValueError(
            "ridge grid must contain at least two unique sorted nonnegative values"
        )
    scales = np.asarray([item.get("scale") for item in records], dtype=float)
    lower = np.asarray([item.get("lower_bound") for item in records], dtype=float)
    upper = np.asarray([item.get("upper_bound") for item in records], dtype=float)
    if (
        not np.all(np.isfinite(scales))
        or not np.all(np.isfinite(lower))
        or not np.all(np.isfinite(upper))
        or np.any(scales <= 0.0)
        or np.any(lower >= upper)
        or np.any(lower > 0.0)
        or np.any(upper < 0.0)
    ):
        raise ValueError(
            "every parameter needs finite positive scale and bounds containing zero"
        )
    if automated:
        rules = policy["coefficient_rules"]
        for item in records:
            basis = str(item.get("basis") or "")
            key = "cosine_dihedral" if basis.startswith("cos(") else basis
            rule = rules.get(key) or {}
            if any(
                item.get(field) != rule.get(field)
                for field in ("scale", "lower_bound", "upper_bound")
            ):
                raise ValueError(
                    "quantitative coefficient rule differs from its pinned policy"
                )
    return spec, scales, lower, upper


def _weighted_system(
    datasets: Sequence[dict[str, Any]], objective: dict[str, Any]
) -> tuple[np.ndarray, np.ndarray]:
    matrices = []
    targets = []
    equalize = objective["dataset_weighting"] == "equal_dataset_rms"
    for dataset in datasets:
        for kind, design_name, target_name, weight_name in (
            (
                "gradient",
                "projected_design_gradient",
                "projected_residual_gradient",
                "gradient_weight",
            ),
            (
                "hessian",
                "projected_design_hessian_upper",
                "projected_residual_hessian_upper",
                "hessian_weight",
            ),
        ):
            design = dataset["arrays"][design_name]
            target = dataset["arrays"][target_name]
            if design.shape[0] == 0:
                raise ValueError(f"response contains an empty {kind} block")
            factor = math.sqrt(float(objective[weight_name]))
            if equalize:
                factor /= math.sqrt(design.shape[0])
            matrices.append(design * factor)
            targets.append(target * factor)
    return np.vstack(matrices), np.concatenate(targets)


def _metrics(
    datasets: Sequence[dict[str, Any]], coefficients: np.ndarray
) -> dict[str, Any]:
    records = []
    all_gradient = []
    all_hessian = []
    for dataset in datasets:
        gradient = (
            dataset["arrays"]["projected_design_gradient"] @ coefficients
            - dataset["arrays"]["projected_residual_gradient"]
        )
        hessian = (
            dataset["arrays"]["projected_design_hessian_upper"] @ coefficients
            - dataset["arrays"]["projected_residual_hessian_upper"]
        )
        all_gradient.append(gradient)
        all_hessian.append(hessian)
        records.append(
            {
                "dataset_id": (
                    f"{dataset['dataset_identity'][0]}:{dataset['dataset_identity'][1]}:"
                    f"{dataset['dataset_identity'][2][:16]}"
                ),
                "gradient_rmse": float(np.sqrt(np.mean(gradient**2))),
                "hessian_rmse": float(np.sqrt(np.mean(hessian**2))),
                "gradient_max_abs": float(np.max(np.abs(gradient))),
                "hessian_max_abs": float(np.max(np.abs(hessian))),
            }
        )
    combined_gradient = np.concatenate(all_gradient)
    combined_hessian = np.concatenate(all_hessian)
    return {
        "dataset_count": len(records),
        "datasets": records,
        "gradient_rmse": float(np.sqrt(np.mean(combined_gradient**2))),
        "hessian_rmse": float(np.sqrt(np.mean(combined_hessian**2))),
        "gradient_max_abs": float(np.max(np.abs(combined_gradient))),
        "hessian_max_abs": float(np.max(np.abs(combined_hessian))),
    }


def evaluate_reviewed_response_fit(
    *, campaign_path: Path, specification_path: Path, output_dir: Path
) -> dict[str, Any]:
    """Fit all reviewed ridge candidates and report holdout errors without selecting."""

    if output_dir.exists():
        raise FileExistsError(
            f"refusing to overwrite response-fit evaluation: {output_dir}"
        )
    try:
        import scipy
        from scipy.optimize import lsq_linear
    except (
        ImportError
    ) as exc:  # pragma: no cover - pinned fitting environment has SciPy
        raise RuntimeError("SciPy is required for bounded response fitting") from exc
    campaign, training, validation = _campaign(campaign_path)
    parameters = campaign.pop("_parameters")
    campaign.pop("_parameter_map_path")
    spec, scales, lower, upper = _reviewed_specification(
        specification_path, campaign_path, parameters, training
    )
    objective = spec["objective"]
    design, target = _weighted_system(training, objective)
    scaled_design = design * scales[None, :]
    lower_scaled = lower / scales
    upper_scaled = upper / scales
    candidates = []
    coefficient_rows = []
    for ridge_lambda in (float(value) for value in objective["ridge_lambdas"]):
        if ridge_lambda > 0.0:
            augmented_design = np.vstack(
                (scaled_design, math.sqrt(ridge_lambda) * np.eye(len(scales)))
            )
            augmented_target = np.concatenate((target, np.zeros(len(scales))))
        else:
            augmented_design, augmented_target = scaled_design, target
        fit = lsq_linear(
            augmented_design,
            augmented_target,
            bounds=(lower_scaled, upper_scaled),
            method="trf",
            tol=1.0e-12,
            lsmr_tol=1.0e-12,
            max_iter=2000,
        )
        if not fit.success or not np.all(np.isfinite(fit.x)):
            raise ValueError(
                f"bounded fit failed for ridge lambda {ridge_lambda}: {fit.message}"
            )
        coefficients = fit.x * scales
        coefficient_rows.append(coefficients)
        candidates.append(
            {
                "ridge_lambda": ridge_lambda,
                "solver_status": int(fit.status),
                "solver_message": str(fit.message),
                "iterations": int(fit.nit or 0),
                "active_bound_count": int(np.count_nonzero(fit.active_mask)),
                "coefficient_l2_scaled": float(np.linalg.norm(fit.x)),
                "training": _metrics(training, coefficients),
                "validation": _metrics(validation, coefficients),
            }
        )
    output_dir.mkdir(parents=True)
    arrays_path = output_dir / "candidate_coefficients.npz"
    np.savez_compressed(
        arrays_path,
        ridge_lambdas=np.asarray(objective["ridge_lambdas"], dtype=float),
        coefficients=np.asarray(coefficient_rows, dtype=float),
        scales=scales,
        lower_bounds=lower,
        upper_bounds=upper,
    )
    report = {
        "schema": "nadoc.photoproduct-response-fit-evaluation.v1",
        "status": "candidate_fits_evaluated_human_selection_required",
        "simulation_ready": False,
        "gate_effect": "none",
        "hypothesis_id": campaign["hypothesis_id"],
        "parameter_count": campaign["parameter_count"],
        "candidate_count": len(candidates),
        "selection": None,
        "software": {
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "solver": "scipy.optimize.lsq_linear",
            "method": "trf",
        },
        "objective": objective,
        "candidates": candidates,
        "sources": {
            "campaign": _source(campaign_path),
            "reviewed_specification": _source(specification_path),
        },
        "outputs": {"candidate_coefficients": _source(arrays_path)},
        "release_blockers": [
            "no ridge candidate or periodicity hypothesis has been selected",
            "bounds, scaling, and force-versus-Hessian weights require sensitivity review",
            "held-out errors require scientific acceptance criteria",
            "DNA-context and NAMD validation remain incomplete",
        ],
        "interpretation": (
            "All candidates used only training responses for optimization and untouched "
            "validation responses for reporting. This comparison does not select parameters, "
            "advance a registry gate, or establish transferability."
        ),
    }
    report_path = output_dir / "response_fit_evaluation.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def select_quantitative_response_fit_candidate(
    *,
    evaluation_path: Path,
    output_path: Path,
    policy_path: Path = RESPONSE_FIT_POLICY_PATH,
) -> dict[str, Any]:
    """Select a smoke-test coefficient row by a preregistered holdout rule."""

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite selected fit candidate: {output_path}"
        )
    evaluation = json.loads(evaluation_path.read_text())
    policy = json.loads(policy_path.read_text())
    if (
        evaluation.get("schema") != "nadoc.photoproduct-response-fit-evaluation.v1"
        or evaluation.get("status")
        != "candidate_fits_evaluated_human_selection_required"
        or evaluation.get("simulation_ready") is not False
        or evaluation.get("gate_effect") != "none"
        or evaluation.get("selection") is not None
        or policy.get("schema") != "nadoc.photoproduct-response-fit-policy.v1"
    ):
        raise ValueError(
            "a neutral fit evaluation and quantitative policy are required"
        )
    specification_path = _checked(
        (evaluation.get("sources") or {}).get("reviewed_specification"),
        "quantitative fit specification",
    )
    specification = json.loads(specification_path.read_text())
    quantitative = specification.get("quantitative_specification") or {}
    if (
        specification.get("status") != "quantitatively_specified"
        or quantitative.get("policy") != policy.get("policy")
        or (quantitative.get("policy_source") or {}).get("sha256")
        != _sha256(policy_path)
        or quantitative.get("releases_parameters") is not False
    ):
        raise ValueError(
            "fit evaluation was not generated from the pinned quantitative policy"
        )
    campaign_path = _checked(
        (evaluation.get("sources") or {}).get("campaign"), "response campaign"
    )
    campaign, training, _validation = _campaign(campaign_path)
    parameters = campaign.pop("_parameters")
    campaign.pop("_parameter_map_path")
    if campaign.get("status") != "training_design_full_rank_diagnostic_only":
        raise ValueError("quantitative selection requires a full-rank training design")
    _reviewed_specification(specification_path, campaign_path, parameters, training)
    coefficients_path = _checked(
        (evaluation.get("outputs") or {}).get("candidate_coefficients"),
        "candidate coefficient array",
    )
    with np.load(coefficients_path, allow_pickle=False) as archive:
        coefficient_rows = np.asarray(archive["coefficients"], dtype=float)
        lower = np.asarray(archive["lower_bounds"], dtype=float)
        upper = np.asarray(archive["upper_bounds"], dtype=float)
        scales = np.asarray(archive["scales"], dtype=float)
    candidates = evaluation.get("candidates") or []
    if coefficient_rows.shape != (len(candidates), len(parameters)):
        raise ValueError("candidate coefficient array differs from evaluation")
    target_rms = quantitative.get("training_target_rms") or {}
    gradient_rms = float(target_rms.get("gradient") or 0.0)
    hessian_rms = float(target_rms.get("hessian") or 0.0)
    if gradient_rms <= 0.0 or hessian_rms <= 0.0:
        raise ValueError("quantitative specification lacks target normalizers")
    eligible = []
    for index, (candidate, coefficients) in enumerate(
        zip(candidates, coefficient_rows, strict=True)
    ):
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
        try:
            transformed = transform_linear_coefficients_to_charmm(parameter_rows)
        except ValueError:
            continue
        if selection_policy := policy.get("candidate_selection"):
            if selection_policy.get("require_stereochemical_basin") is True:
                expected_by_group = {
                    item["group_id"]: item.get("expected_signed_volume")
                    for item in parameter_rows
                    if item.get("category") == "impropers"
                }
                if not expected_by_group or any(
                    expected_by_group.get(item["group_id"])
                    not in {"positive", "negative"}
                    or (
                        expected_by_group[item["group_id"]] == "positive"
                        and float(item["psi0_degrees"]) <= 0.0
                    )
                    or (
                        expected_by_group[item["group_id"]] == "negative"
                        and float(item["psi0_degrees"]) >= 0.0
                    )
                    for item in transformed["impropers"]
                ):
                    continue
        validation = candidate["validation"]
        score = (float(validation["gradient_rmse"]) / gradient_rms) ** 2 + (
            float(validation["hessian_rmse"]) / hessian_rms
        ) ** 2
        if math.isfinite(score):
            eligible.append(
                {
                    "index": index,
                    "score": score,
                    "candidate": candidate,
                    "parameters": parameter_rows,
                }
            )
    if not eligible:
        raise ValueError("no response-fit candidate has a physical CHARMM transform")
    selection_policy = policy["candidate_selection"]
    if "near_best_relative_window" in selection_policy:
        window_fraction = float(selection_policy["near_best_relative_window"])
        tie_breakers = selection_policy.get("tie_breakers") or []
        expected_tie_breakers = [
            "fewest_active_bounds",
            "smallest_scaled_coefficient_norm",
            "largest_ridge_lambda",
            "smallest_raw_validation_score",
        ]
        if tie_breakers != expected_tie_breakers:
            raise ValueError("unsupported quantitative candidate tie-break policy")

        def selection_key(item: dict[str, Any]) -> tuple[float, ...]:
            candidate = item["candidate"]
            return (
                float(candidate["active_bound_count"]),
                float(candidate["coefficient_l2_scaled"]),
                -float(candidate["ridge_lambda"]),
                float(item["score"]),
            )

    else:
        window_fraction = float(selection_policy["simplicity_window_fraction"])

        def selection_key(item: dict[str, Any]) -> tuple[float, ...]:
            candidate = item["candidate"]
            return (
                float(candidate["active_bound_count"]),
                -float(candidate["ridge_lambda"]),
                float(candidate["coefficient_l2_scaled"]),
            )

    if not math.isfinite(window_fraction) or window_fraction < 0.0:
        raise ValueError("candidate selection window must be finite and non-negative")
    best_score = min(item["score"] for item in eligible)
    window = best_score * (1.0 + window_fraction)
    finalists = [item for item in eligible if item["score"] <= window + 1.0e-15]
    selected = min(finalists, key=selection_key)
    candidate = selected["candidate"]
    report = {
        "schema": "nadoc.photoproduct-selected-response-fit-candidate.v1",
        "status": "quantitatively_selected_candidate_requires_charmm_mapping_and_validation",
        "simulation_ready": False,
        "gate_effect": "none",
        "hypothesis_id": evaluation["hypothesis_id"],
        "ridge_lambda": candidate["ridge_lambda"],
        "selection_checks": {
            "full_rank_training_design": {"passed": True},
            "physical_charmm_transform": {"passed": True},
            "within_validation_score_window": {
                "passed": True,
                "value": selected["score"],
                "best_value": best_score,
                "maximum": window,
            },
        },
        "decision_authority": {
            "kind": "automated_quantitative_policy",
            "policy": policy["policy"],
            "policy_source": _source(policy_path),
            "releases_parameters": False,
        },
        "training_metrics": candidate["training"],
        "validation_metrics": candidate["validation"],
        "parameters": selected["parameters"],
        "sources": {
            "fit_evaluation": _source(evaluation_path),
            "candidate_coefficients": _source(coefficients_path),
            "campaign": _source(campaign_path),
            "quantitative_specification": _source(specification_path),
            "quantitative_selection_policy": _source(policy_path),
        },
        "release_blockers": [
            "linear coefficients have not been transformed into final CHARMM terms",
            "MM geometry and conformer-energy validation remain incomplete",
            "topology, charge, nonbonded, DNA context, psfgen, and NAMD validation remain independent",
        ],
        "interpretation": (
            "This training-only fit was selected by a preregistered held-out score and "
            "physical-transform screen. It is a smoke-test candidate, not a released "
            "CHARMM parameter set or simulation-ready product."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def compare_response_fit_evaluations(
    *, evaluation_paths: Sequence[Path], output_path: Path
) -> dict[str, Any]:
    """Collate nested-hypothesis holdout results without ranking or selecting them."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite fit comparison: {output_path}")
    if len(evaluation_paths) < 2:
        raise ValueError("at least two response-fit evaluations are required")
    records = []
    hypothesis_ids = set()
    reference_training = None
    reference_validation = None
    for path in evaluation_paths:
        evaluation = json.loads(path.read_text())
        if (
            evaluation.get("schema") != "nadoc.photoproduct-response-fit-evaluation.v1"
            or evaluation.get("status")
            != "candidate_fits_evaluated_human_selection_required"
            or evaluation.get("simulation_ready") is not False
            or evaluation.get("gate_effect") != "none"
            or evaluation.get("selection") is not None
            or not isinstance(evaluation.get("candidates"), list)
            or len(evaluation["candidates"]) != evaluation.get("candidate_count")
        ):
            raise ValueError(f"{path}: non-selecting response-fit evaluation required")
        coefficients_path = _checked(
            (evaluation.get("outputs") or {}).get("candidate_coefficients"),
            f"{path} candidate coefficients",
        )
        with np.load(coefficients_path, allow_pickle=False) as archive:
            if (
                "coefficients" not in archive
                or "ridge_lambdas" not in archive
                or archive["coefficients"].shape
                != (evaluation["candidate_count"], evaluation["parameter_count"])
                or archive["ridge_lambdas"].tolist()
                != [item.get("ridge_lambda") for item in evaluation["candidates"]]
            ):
                raise ValueError(f"{path}: coefficient archive differs from evaluation")
        campaign_path = _checked(
            (evaluation.get("sources") or {}).get("campaign"),
            f"{path} campaign",
        )
        _checked(
            (evaluation.get("sources") or {}).get("reviewed_specification"),
            f"{path} reviewed specification",
        )
        campaign, _training, _validation = _campaign(campaign_path)
        campaign.pop("_parameter_map_path")
        campaign.pop("_parameters")
        hypothesis_id = evaluation.get("hypothesis_id")
        if (
            not isinstance(hypothesis_id, str)
            or not hypothesis_id
            or hypothesis_id != campaign.get("hypothesis_id")
            or hypothesis_id in hypothesis_ids
        ):
            raise ValueError("fit evaluations require distinct matching hypothesis IDs")
        hypothesis_ids.add(hypothesis_id)
        training_ids = [item["dataset_id"] for item in campaign["training_datasets"]]
        validation_ids = [
            item["dataset_id"] for item in campaign["validation_datasets"]
        ]
        if reference_training is None:
            reference_training = training_ids
            reference_validation = validation_ids
        elif (
            training_ids != reference_training or validation_ids != reference_validation
        ):
            raise ValueError(
                "fit evaluations do not use identical ordered physical train/holdout datasets"
            )
        records.append(
            {
                "hypothesis_id": hypothesis_id,
                "parameter_count": evaluation["parameter_count"],
                "candidate_count": evaluation["candidate_count"],
                "objective": evaluation["objective"],
                "candidates": evaluation["candidates"],
                "evaluation": _source(path),
                "candidate_coefficients": _source(coefficients_path),
            }
        )
    report = {
        "schema": "nadoc.photoproduct-response-fit-comparison.v1",
        "status": "human_hypothesis_and_regularization_selection_required",
        "simulation_ready": False,
        "gate_effect": "none",
        "selection": None,
        "training_dataset_ids": reference_training,
        "validation_dataset_ids": reference_validation,
        "hypotheses": records,
        "release_blockers": [
            "no periodicity hypothesis or ridge candidate has been selected",
            "objective weights and coefficient bounds require sensitivity review",
            "validation acceptance thresholds require scientific justification",
            "selected coefficients still require topology and NAMD context validation",
        ],
        "interpretation": (
            "Every hypothesis was trained and evaluated independently against the exact same "
            "ordered physical datasets. This artifact preserves results for human review; it "
            "does not rank candidates, advance a force-field gate, or imply simulation readiness."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def _validated_comparison(path: Path) -> dict[str, Any]:
    comparison = json.loads(path.read_text())
    hypotheses = comparison.get("hypotheses") or []
    if (
        comparison.get("schema") != "nadoc.photoproduct-response-fit-comparison.v1"
        or comparison.get("status")
        != "human_hypothesis_and_regularization_selection_required"
        or comparison.get("simulation_ready") is not False
        or comparison.get("gate_effect") != "none"
        or comparison.get("selection") is not None
        or len(hypotheses) < 2
        or len({item.get("hypothesis_id") for item in hypotheses}) != len(hypotheses)
    ):
        raise ValueError("a neutral unselected response-fit comparison is required")
    for record in hypotheses:
        evaluation_path = _checked(
            record.get("evaluation"), f"{record.get('hypothesis_id')} evaluation"
        )
        evaluation = json.loads(evaluation_path.read_text())
        coefficients_path = _checked(
            record.get("candidate_coefficients"),
            f"{record.get('hypothesis_id')} coefficient array",
        )
        if (
            evaluation.get("schema") != "nadoc.photoproduct-response-fit-evaluation.v1"
            or evaluation.get("status")
            != "candidate_fits_evaluated_human_selection_required"
            or evaluation.get("selection") is not None
            or evaluation.get("hypothesis_id") != record.get("hypothesis_id")
            or evaluation.get("parameter_count") != record.get("parameter_count")
            or evaluation.get("candidate_count") != record.get("candidate_count")
            or evaluation.get("objective") != record.get("objective")
            or evaluation.get("candidates") != record.get("candidates")
            or (evaluation.get("outputs") or {})
            .get("candidate_coefficients", {})
            .get("sha256")
            != _sha256(coefficients_path)
        ):
            raise ValueError("comparison hypothesis differs from its fit evaluation")
    return comparison


def build_response_fit_selection_template(
    *, comparison_path: Path, output_path: Path
) -> dict[str, Any]:
    """Create a null selection form; software does not nominate a candidate."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite fit selection: {output_path}")
    comparison = _validated_comparison(comparison_path)
    report = {
        "schema": "nadoc.photoproduct-response-fit-selection.v1",
        "status": "review_required",
        "simulation_ready": False,
        "gate_effect": "none",
        "comparison": _source(comparison_path),
        "reviewed_by": None,
        "reviewed_at": None,
        "review_rationale": None,
        "selection": {"hypothesis_id": None, "ridge_lambda": None},
        "acceptance_limits": {
            "validation_gradient_rmse_max": None,
            "validation_hessian_rmse_max": None,
            "validation_gradient_max_abs_max": None,
            "validation_hessian_max_abs_max": None,
            "active_bound_count_max": None,
        },
        "available_hypotheses": [
            {
                "hypothesis_id": item["hypothesis_id"],
                "parameter_count": item["parameter_count"],
                "ridge_lambdas": [
                    candidate["ridge_lambda"] for candidate in item["candidates"]
                ],
            }
            for item in comparison["hypotheses"]
        ],
        "instructions": (
            "A qualified reviewer must choose one existing hypothesis/ridge pair, provide "
            "scientifically justified validation error and active-bound limits, and explain "
            "the complexity/regularization decision. Passing these declared limits creates "
            "only a selected candidate bundle, never a released force field."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def extract_reviewed_response_fit_candidate(
    *, selection_path: Path, output_path: Path
) -> dict[str, Any]:
    """Extract one explicitly reviewed coefficient row without mapping it to CHARMM."""

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite selected fit candidate: {output_path}"
        )
    selection = json.loads(selection_path.read_text())
    choice = selection.get("selection") or {}
    limits = selection.get("acceptance_limits") or {}
    if (
        selection.get("schema") != "nadoc.photoproduct-response-fit-selection.v1"
        or selection.get("status") != "reviewed"
        or selection.get("simulation_ready") is not False
        or selection.get("gate_effect") != "none"
        or not isinstance(selection.get("reviewed_by"), str)
        or not selection["reviewed_by"].strip()
        or not _timestamp(selection.get("reviewed_at"))
        or not isinstance(selection.get("review_rationale"), str)
        or len(selection["review_rationale"].strip()) < 30
        or not isinstance(choice.get("hypothesis_id"), str)
        or not choice["hypothesis_id"]
        or not isinstance(choice.get("ridge_lambda"), (int, float))
        or not math.isfinite(float(choice["ridge_lambda"]))
    ):
        raise ValueError("fit selection lacks a complete explicit human review")
    numeric_limit_names = (
        "validation_gradient_rmse_max",
        "validation_hessian_rmse_max",
        "validation_gradient_max_abs_max",
        "validation_hessian_max_abs_max",
    )
    if any(
        not isinstance(limits.get(name), (int, float))
        or not math.isfinite(float(limits[name]))
        or float(limits[name]) <= 0.0
        for name in numeric_limit_names
    ) or (
        not isinstance(limits.get("active_bound_count_max"), int)
        or limits["active_bound_count_max"] < 0
    ):
        raise ValueError("fit selection requires finite positive validation limits")
    comparison_path = _checked(selection.get("comparison"), "fit comparison")
    comparison = _validated_comparison(comparison_path)
    matches = [
        item
        for item in comparison["hypotheses"]
        if item["hypothesis_id"] == choice["hypothesis_id"]
    ]
    if len(matches) != 1:
        raise ValueError("selected hypothesis is absent or ambiguous")
    hypothesis = matches[0]
    ridge_lambda = float(choice["ridge_lambda"])
    candidate_indices = [
        index
        for index, item in enumerate(hypothesis["candidates"])
        if float(item["ridge_lambda"]) == ridge_lambda
    ]
    if len(candidate_indices) != 1:
        raise ValueError("selected ridge value is absent or ambiguous")
    candidate_index = candidate_indices[0]
    candidate = hypothesis["candidates"][candidate_index]
    validation = candidate["validation"]
    checks = {
        "validation_gradient_rmse": {
            "value": validation["gradient_rmse"],
            "maximum": limits["validation_gradient_rmse_max"],
        },
        "validation_hessian_rmse": {
            "value": validation["hessian_rmse"],
            "maximum": limits["validation_hessian_rmse_max"],
        },
        "validation_gradient_max_abs": {
            "value": validation["gradient_max_abs"],
            "maximum": limits["validation_gradient_max_abs_max"],
        },
        "validation_hessian_max_abs": {
            "value": validation["hessian_max_abs"],
            "maximum": limits["validation_hessian_max_abs_max"],
        },
        "active_bound_count": {
            "value": candidate["active_bound_count"],
            "maximum": limits["active_bound_count_max"],
        },
    }
    for check in checks.values():
        check["passed"] = check["value"] <= check["maximum"]
    if not all(check["passed"] for check in checks.values()):
        raise ValueError(
            "selected fit candidate exceeds a reviewer-declared acceptance limit"
        )

    evaluation_path = _checked(hypothesis["evaluation"], "selected fit evaluation")
    evaluation = json.loads(evaluation_path.read_text())
    coefficients_path = _checked(
        hypothesis["candidate_coefficients"], "selected coefficient array"
    )
    with np.load(coefficients_path, allow_pickle=False) as archive:
        coefficients = np.asarray(archive["coefficients"][candidate_index], dtype=float)
        lower = np.asarray(archive["lower_bounds"], dtype=float)
        upper = np.asarray(archive["upper_bounds"], dtype=float)
        scales = np.asarray(archive["scales"], dtype=float)
    if (
        coefficients.shape != (hypothesis["parameter_count"],)
        or any(array.shape != coefficients.shape for array in (lower, upper, scales))
        or not np.all(np.isfinite(coefficients))
        or np.any(coefficients < lower - 1.0e-10)
        or np.any(coefficients > upper + 1.0e-10)
    ):
        raise ValueError(
            "selected coefficient row is malformed or outside reviewed bounds"
        )
    campaign_path = _checked(
        (evaluation.get("sources") or {}).get("campaign"), "selected fit campaign"
    )
    campaign, _training, _validation = _campaign(campaign_path)
    parameters = campaign.pop("_parameters")
    campaign.pop("_parameter_map_path")
    if len(parameters) != len(coefficients):
        raise ValueError("selected coefficients and parameter map differ")
    report = {
        "schema": "nadoc.photoproduct-selected-response-fit-candidate.v1",
        "status": "human_selected_candidate_requires_charmm_mapping_and_validation",
        "simulation_ready": False,
        "gate_effect": "none",
        "hypothesis_id": hypothesis["hypothesis_id"],
        "ridge_lambda": ridge_lambda,
        "selection_checks": checks,
        "training_metrics": candidate["training"],
        "validation_metrics": candidate["validation"],
        "parameters": [
            {
                "name": parameter["name"],
                "group_id": parameter.get("group_id"),
                "category": parameter.get("category"),
                "basis": parameter.get("basis"),
                "coefficient_units": parameter.get("coefficient_units"),
                "periodicity": parameter.get("periodicity"),
                "reference_degrees": parameter.get("reference_degrees"),
                "ordered_atoms_candidate": parameter.get("ordered_atoms_candidate"),
                "occurrence_count": parameter.get("occurrence_count"),
                "coefficient": float(value),
                "scale": float(scale),
                "lower_bound": float(minimum),
                "upper_bound": float(maximum),
            }
            for parameter, value, scale, minimum, maximum in zip(
                parameters, coefficients, scales, lower, upper, strict=True
            )
        ],
        "sources": {
            "reviewed_selection": _source(selection_path),
            "comparison": _source(comparison_path),
            "fit_evaluation": _source(evaluation_path),
            "candidate_coefficients": _source(coefficients_path),
            "campaign": _source(campaign_path),
        },
        "release_blockers": [
            "linear coefficients have not been transformed into reviewed CHARMM terms",
            "topology, charge, nonbonded, improper, and context validation remain independent",
            "real psfgen and NAMD validation have not passed for this candidate",
        ],
        "interpretation": (
            "This is a human-selected linear-response candidate with declared holdout limits. "
            "It is not a CHARMM parameter file, registry-gate pass, or simulation-ready product."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def transform_linear_coefficients_to_charmm(
    parameters: Sequence[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Apply only the exact algebraic inverse of the declared linear basis."""

    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    names = set()
    for parameter in parameters:
        name = parameter.get("name")
        group_id = parameter.get("group_id")
        coefficient = parameter.get("coefficient")
        if (
            not isinstance(name, str)
            or not name
            or name in names
            or not isinstance(group_id, str)
            or not group_id
            or not isinstance(coefficient, (int, float))
            or not math.isfinite(float(coefficient))
        ):
            raise ValueError("linear coefficient table is malformed or ambiguous")
        names.add(name)
        if group_id not in groups:
            groups[group_id] = []
            order.append(group_id)
        groups[group_id].append(parameter)
    transformed = {"bonds": [], "angles": [], "dihedrals": [], "impropers": []}
    for group_id in order:
        records = groups[group_id]
        categories = {item.get("category") for item in records}
        occurrences = {item.get("occurrence_count") for item in records}
        if len(categories) != 1 or len(occurrences) != 1:
            raise ValueError(f"linear fit group {group_id} has inconsistent identity")
        category = next(iter(categories))
        by_basis = {item.get("basis"): item for item in records}
        if len(by_basis) != len(records):
            raise ValueError(f"linear fit group {group_id} repeats a basis function")
        if category == "bonds":
            required = {"r^2", "r"}
            if set(by_basis) != required:
                raise ValueError(f"bond fit group {group_id} lacks its complete basis")
            if (
                by_basis["r^2"].get("coefficient_units") != "kcal/mol/angstrom^2"
                or by_basis["r"].get("coefficient_units") != "kcal/mol/angstrom"
            ):
                raise ValueError(f"bond fit group {group_id} has incompatible units")
            bond_k = float(by_basis["r^2"]["coefficient"])
            if bond_k <= 0.0:
                raise ValueError(f"bond fit group {group_id} has nonpositive curvature")
            r0 = -float(by_basis["r"]["coefficient"]) / (2.0 * bond_k)
            if not 0.5 < r0 < 3.0:
                raise ValueError(
                    f"bond fit group {group_id} has an invalid equilibrium"
                )
            transformed["bonds"].append(
                {
                    "group_id": group_id,
                    "occurrence_count": next(iter(occurrences)),
                    "k_kcal_mol_a2": bond_k,
                    "r0_angstrom": r0,
                    "source_coefficients": [item["name"] for item in records],
                }
            )
            continue
        if category == "angles":
            allowed = (
                {"theta^2", "theta"},
                {"theta^2", "theta", "r13^2", "r13"},
            )
            if set(by_basis) not in allowed:
                raise ValueError(f"angle fit group {group_id} lacks its complete basis")
            expected_units = {
                "theta^2": "kcal/mol/rad^2",
                "theta": "kcal/mol/rad",
            }
            if "r13^2" in by_basis:
                expected_units.update(
                    {
                        "r13^2": "kcal/mol/angstrom^2",
                        "r13": "kcal/mol/angstrom",
                    }
                )
            if any(
                by_basis[basis].get("coefficient_units") != units
                for basis, units in expected_units.items()
            ):
                raise ValueError(f"angle fit group {group_id} has incompatible units")
            angle_k = float(by_basis["theta^2"]["coefficient"])
            angle_linear = float(by_basis["theta"]["coefficient"])
            if angle_k <= 0.0:
                raise ValueError(
                    f"angle fit group {group_id} has nonpositive curvature"
                )
            theta0 = -angle_linear / (2.0 * angle_k)
            if not 0.0 < theta0 < math.pi:
                raise ValueError(
                    f"angle fit group {group_id} has an invalid equilibrium"
                )
            if "r13^2" not in by_basis:
                urey_bradley = None
            else:
                ub_k = float(by_basis["r13^2"]["coefficient"])
                ub_linear = float(by_basis["r13"]["coefficient"])
                if abs(ub_k) <= 1.0e-14 and abs(ub_linear) <= 1.0e-14:
                    urey_bradley = None
                elif ub_k <= 0.0:
                    raise ValueError(
                        f"angle fit group {group_id} has nonpositive Urey-Bradley curvature"
                    )
                else:
                    ub_r0 = -ub_linear / (2.0 * ub_k)
                    if ub_r0 <= 0.0:
                        raise ValueError(
                            f"angle fit group {group_id} has an invalid Urey-Bradley distance"
                        )
                    urey_bradley = {
                        "k_kcal_mol_angstrom2": ub_k,
                        "s0_angstrom": ub_r0,
                    }
            transformed["angles"].append(
                {
                    "group_id": group_id,
                    "occurrence_count": next(iter(occurrences)),
                    "k_kcal_mol_rad2": angle_k,
                    "theta0_degrees": math.degrees(theta0),
                    "urey_bradley": urey_bradley,
                    "source_coefficients": [item["name"] for item in records],
                }
            )
            continue
        if category == "dihedrals":
            terms = []
            periodicities = set()
            for record in records:
                periodicity = record.get("periodicity")
                if (
                    not isinstance(periodicity, int)
                    or periodicity < 1
                    or periodicity > 6
                    or periodicity in periodicities
                    or record.get("basis") != f"cos({periodicity}*phi)"
                    or record.get("coefficient_units") != "kcal/mol"
                ):
                    raise ValueError(f"dihedral fit group {group_id} is malformed")
                periodicities.add(periodicity)
                coefficient = float(record["coefficient"])
                terms.append(
                    {
                        "periodicity": periodicity,
                        "k_kcal_mol": abs(coefficient),
                        "delta_degrees": 0.0 if coefficient >= 0.0 else 180.0,
                        "source_coefficient": record["name"],
                    }
                )
            transformed["dihedrals"].append(
                {
                    "group_id": group_id,
                    "occurrence_count": next(iter(occurrences)),
                    "fourier_terms": sorted(
                        terms, key=lambda item: item["periodicity"]
                    ),
                }
            )
            continue
        if category == "impropers":
            allowed = (
                {"wrapped_delta^2"},
                {"wrapped_delta^2", "wrapped_delta"},
            )
            if set(by_basis) not in allowed:
                raise ValueError(
                    f"improper fit group {group_id} lacks its complete basis"
                )
            quadratic = by_basis["wrapped_delta^2"]
            linear = by_basis.get("wrapped_delta")
            if quadratic.get("coefficient_units") != "kcal/mol/rad^2" or (
                linear is not None
                and (
                    linear.get("coefficient_units") != "kcal/mol/rad"
                    or quadratic.get("reference_degrees")
                    != linear.get("reference_degrees")
                    or quadratic.get("ordered_atoms_candidate")
                    != linear.get("ordered_atoms_candidate")
                )
            ):
                raise ValueError(
                    f"improper fit group {group_id} has inconsistent identity"
                )
            improper_k = float(quadratic["coefficient"])
            if improper_k <= 0.0:
                raise ValueError(
                    f"improper fit group {group_id} has nonpositive curvature"
                )
            offset = (
                -float(linear["coefficient"]) / (2.0 * improper_k)
                if linear is not None
                else 0.0
            )
            if not -math.pi < offset < math.pi:
                raise ValueError(
                    f"improper fit group {group_id} equilibrium crosses wrapping"
                )
            reference = float(quadratic["reference_degrees"])
            psi0 = (reference + math.degrees(offset) + 180.0) % 360.0 - 180.0
            transformed["impropers"].append(
                {
                    "group_id": group_id,
                    "occurrence_count": next(iter(occurrences)),
                    "ordered_atoms_candidate": quadratic["ordered_atoms_candidate"],
                    "k_kcal_mol_rad2": improper_k,
                    "psi0_degrees": psi0,
                    "source_coefficients": [quadratic["name"]]
                    + ([linear["name"]] if linear is not None else []),
                }
            )
            continue
        raise ValueError(f"unsupported linear fit category {category!r}")
    return transformed


def build_charmm_bonded_transform_candidate(
    *, selected_candidate_path: Path, output_path: Path
) -> dict[str, Any]:
    """Transform a hash-valid selected row while retaining all release blockers."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite CHARMM transform: {output_path}")
    selected = json.loads(selected_candidate_path.read_text())
    automated = selected.get("status") == (
        "quantitatively_selected_candidate_requires_charmm_mapping_and_validation"
    )
    if (
        selected.get("schema")
        != "nadoc.photoproduct-selected-response-fit-candidate.v1"
        or selected.get("status")
        not in {
            "human_selected_candidate_requires_charmm_mapping_and_validation",
            "quantitatively_selected_candidate_requires_charmm_mapping_and_validation",
        }
        or selected.get("simulation_ready") is not False
        or selected.get("gate_effect") != "none"
        or not selected.get("parameters")
        or not all(
            item.get("passed") is True
            for item in (selected.get("selection_checks") or {}).values()
        )
    ):
        raise ValueError(
            "a passed human or quantitatively selected response-fit candidate is required"
        )
    sources = selected.get("sources") or {}
    evaluation_path = _checked(sources.get("fit_evaluation"), "fit evaluation")
    coefficients_path = _checked(
        sources.get("candidate_coefficients"), "candidate coefficients"
    )
    campaign_path = _checked(sources.get("campaign"), "response campaign")
    evaluation = json.loads(evaluation_path.read_text())
    campaign, _training, _validation = _campaign(campaign_path)
    parameter_map = campaign.pop("_parameters")
    campaign.pop("_parameter_map_path")
    selected_ridge = selected.get("ridge_lambda")
    if automated:
        policy_path = _checked(
            sources.get("quantitative_selection_policy"),
            "quantitative selection policy",
        )
        specification_path = _checked(
            sources.get("quantitative_specification"),
            "quantitative fit specification",
        )
        policy = json.loads(policy_path.read_text())
        specification = json.loads(specification_path.read_text())
        authority = selected.get("decision_authority") or {}
        provenance_invalid = (
            policy.get("schema") != "nadoc.photoproduct-response-fit-policy.v1"
            or specification.get("status") != "quantitatively_specified"
            or authority.get("kind") != "automated_quantitative_policy"
            or authority.get("policy") != policy.get("policy")
            or authority.get("policy_source") != _source(policy_path)
            or authority.get("releases_parameters") is not False
            or (evaluation.get("sources") or {}).get("reviewed_specification")
            != _source(specification_path)
        )
    else:
        selection_path = _checked(
            sources.get("reviewed_selection"), "reviewed selection"
        )
        comparison_path = _checked(sources.get("comparison"), "fit comparison")
        selection = json.loads(selection_path.read_text())
        _validated_comparison(comparison_path)
        selection_choice = selection.get("selection") or {}
        reviewed_ridge = selection_choice.get("ridge_lambda")
        provenance_invalid = (
            (selection.get("comparison") or {}).get("sha256")
            != _sha256(comparison_path)
            or selection_choice.get("hypothesis_id") != selected.get("hypothesis_id")
            or isinstance(reviewed_ridge, bool)
            or not isinstance(reviewed_ridge, (int, float))
            or not math.isfinite(float(reviewed_ridge))
            or isinstance(selected_ridge, bool)
            or not isinstance(selected_ridge, (int, float))
            or not math.isfinite(float(selected_ridge))
            or float(reviewed_ridge) != float(selected_ridge)
        )
    if (
        provenance_invalid
        or isinstance(selected_ridge, bool)
        or not isinstance(selected_ridge, (int, float))
        or not math.isfinite(float(selected_ridge))
        or evaluation.get("hypothesis_id") != selected.get("hypothesis_id")
        or campaign.get("hypothesis_id") != selected.get("hypothesis_id")
    ):
        raise ValueError("selected response-fit provenance chain changed identity")
    ridge_values = [
        float(item["ridge_lambda"]) for item in evaluation.get("candidates") or []
    ]
    indices = [
        index
        for index, value in enumerate(ridge_values)
        if value == float(selected_ridge)
    ]
    if len(indices) != 1:
        raise ValueError("selected response-fit ridge row is absent or ambiguous")
    with np.load(coefficients_path, allow_pickle=False) as archive:
        coefficients = np.asarray(archive["coefficients"][indices[0]], dtype=float)
    identity_fields = (
        "name",
        "group_id",
        "category",
        "basis",
        "coefficient_units",
        "periodicity",
        "reference_degrees",
        "ordered_atoms_candidate",
        "occurrence_count",
    )
    selected_parameters = selected["parameters"]
    if (
        len(selected_parameters) != len(parameter_map)
        or coefficients.shape != (len(parameter_map),)
        or any(
            tuple(observed.get(field) for field in identity_fields)
            != tuple(expected.get(field) for field in identity_fields)
            for observed, expected in zip(
                selected_parameters, parameter_map, strict=True
            )
        )
        or not np.array_equal(
            coefficients,
            np.asarray([item["coefficient"] for item in selected_parameters]),
        )
    ):
        raise ValueError(
            "selected response-fit coefficients or parameter identity changed"
        )
    transformed = transform_linear_coefficients_to_charmm(selected_parameters)
    report = {
        "schema": "nadoc.photoproduct-charmm-bonded-transform-candidate.v1",
        "status": "algebraically_transformed_requires_term_mapping_and_validation",
        "simulation_ready": False,
        "gate_effect": "none",
        "hypothesis_id": selected["hypothesis_id"],
        "ridge_lambda": selected["ridge_lambda"],
        "bonded_terms": transformed,
        "selection_authority": (
            "automated_quantitative_policy" if automated else "human_review"
        ),
        "sources": {
            "selected_response_fit_candidate": _source(selected_candidate_path)
        },
        "release_blockers": [
            "fit-group occurrences have not been mapped to final reviewed CHARMM atom types",
            "additive constants and shared parameter occurrences require consistency review",
            "charges, Lennard-Jones terms, topology, and improper removal remain independent",
            "MM minima, DNA contexts, psfgen, and NAMD have not been validated",
        ],
        "interpretation": (
            "This applies only the declared algebraic inverse of the linear fitting basis. "
            "It is not a parameter file and cannot pass a force-field or simulation gate."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
