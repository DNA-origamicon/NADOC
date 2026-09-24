"""Training-only objective decomposition along fixed-equilibrium H6 stiffness."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source, write
from backend.parameterization.photoproduct_response_fit import (
    _campaign,
    _weighted_system,
)


def main(stage, fit_path, output):
    campaign_path = stage / "response_campaign/response_campaign_manifest.json"
    # _campaign validates all source hashes; only training arrays enter this audit.
    _, training, _ = _campaign(campaign_path)
    spec = json.loads((stage / "quantitative_fit_specification.json").read_text())
    fit = json.loads(fit_path.read_text())
    parameters = fit["parameters"]
    assert [p["name"] for p in parameters] == [p["name"] for p in spec["parameters"]]
    coefficients = np.array([p["coefficient"] for p in parameters])
    scales = np.array([p["scale"] for p in parameters])
    objective = spec["objective"]
    assert objective["dataset_weighting"] == "equal_dataset_rms"
    ids = {
        p["basis"]: i
        for i, p in enumerate(parameters)
        if p["group_id"] == "bonds:drude-hydrogen-C6-H6"
    }
    k = coefficients[ids["r^2"]]
    r0 = -coefficients[ids["r"]] / (2 * k)
    direction = np.zeros_like(coefficients)
    direction[ids["r^2"]] = 1
    direction[ids["r"]] = -2 * r0
    blocks = []
    for data in training:
        manifest = json.loads(data["manifest_path"].read_text())
        is_min = manifest["target"]["kind"] == "audited_harmonic_minimum"
        for kind, design_key, target_key in [
            ("gradient", "projected_design_gradient", "projected_residual_gradient"),
            (
                "hessian",
                "projected_design_hessian_upper",
                "projected_residual_hessian_upper",
            ),
        ]:
            a = data["arrays"][design_key]
            b = data["arrays"][target_key]
            weight = objective[kind + "_weight"] / len(b)
            if is_min and kind == "gradient":
                weight *= 10
            residual = a @ coefficients - b
            tangent = a @ direction
            derivative = float(weight * residual @ tangent)
            curvature = float(weight * tangent @ tangent)
            blocks.append(
                {
                    "dataset": str(data["manifest_path"]),
                    "audited_minimum": is_min,
                    "kind": kind,
                    "row_count": len(b),
                    "per_row_squared_weight": weight,
                    "half_squared_objective": float(0.5 * weight * residual @ residual),
                    "derivative_per_unit_k": derivative,
                    "curvature_per_unit_k_squared": curvature,
                    "conditional_block_optimal_k": float(k - derivative / curvature)
                    if curvature > 1e-20
                    else None,
                }
            )
    ridge = fit["ridge_lambda"]
    derivative = float(ridge * (coefficients / scales) @ (direction / scales))
    curvature = float(ridge * np.sum((direction / scales) ** 2))
    blocks.append(
        {
            "kind": "ridge",
            "half_squared_objective": float(
                0.5 * ridge * np.sum((coefficients / scales) ** 2)
            ),
            "derivative_per_unit_k": derivative,
            "curvature_per_unit_k_squared": curvature,
            "conditional_block_optimal_k": float(k - derivative / curvature),
        }
    )
    totals = {
        kind: {
            "derivative": sum(
                b["derivative_per_unit_k"] for b in blocks if b["kind"] == kind
            ),
            "curvature": sum(
                b["curvature_per_unit_k_squared"] for b in blocks if b["kind"] == kind
            ),
            "half_squared_objective": sum(
                b["half_squared_objective"] for b in blocks if b["kind"] == kind
            ),
        }
        for kind in ("gradient", "hessian", "ridge")
    }
    total_d = sum(b["derivative_per_unit_k"] for b in blocks)
    total_h = sum(b["curvature_per_unit_k_squared"] for b in blocks)
    # Independent finite difference of the actual assembled objective.
    a, b = _weighted_system(training, objective)
    minimum = next(
        d["arrays"]
        for d in training
        if json.loads(d["manifest_path"].read_text())["target"]["kind"]
        == "audited_harmonic_minimum"
    )
    factor = np.sqrt(
        9 * objective["gradient_weight"] / len(minimum["projected_residual_gradient"])
    )
    a = np.vstack([a, factor * minimum["projected_design_gradient"]])
    b = np.concatenate([b, factor * minimum["projected_residual_gradient"]])

    def loss(delta):
        c = coefficients + delta * direction
        return 0.5 * (np.sum((a @ c - b) ** 2) + ridge * np.sum((c / scales) ** 2))

    step = 0.01
    finite = (loss(step) - loss(-step)) / (2 * step)
    assert abs(finite - total_d) < 1e-9
    report = {
        "simulation_ready": False,
        "gate_effect": "none",
        "scope": "Training objective decomposition, not a refit or proposed replacement parameter. Conditional optima hold all other coefficients and H6 equilibrium length fixed.",
        "fit": source(fit_path),
        "campaign": source(campaign_path),
        "code": source(Path(__file__)),
        "current_k": float(k),
        "fixed_r0_angstrom": float(r0),
        "blocks": blocks,
        "totals_by_kind": totals,
        "total_directional_derivative": total_d,
        "finite_difference_derivative": finite,
        "conditional_total_optimal_k": float(k - total_d / total_h),
        "parameters_changed": False,
    }
    write(output, report)
    print(
        json.dumps(
            {
                "current_k": float(k),
                "totals": totals,
                "total_derivative": total_d,
                "conditional_total_optimal_k": report["conditional_total_optimal_k"],
                "conditional_block_optima": [
                    (
                        r["kind"],
                        r.get("audited_minimum"),
                        r["conditional_block_optimal_k"],
                    )
                    for r in blocks
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--stage", required=True, type=Path)
    p.add_argument("--fit", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    main(a.stage, a.fit, a.output)
