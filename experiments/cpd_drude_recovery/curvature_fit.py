"""Training-minimum H6 force/curvature constrained diagnostic; never a release selector."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import LinearConstraint, minimize

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source, write, checked
from backend.parameterization.photoproduct_qm import parse_xyz
from backend.parameterization.photoproduct_response_fit import (
    _campaign,
    _weighted_system,
    _physical_equilibrium_constraint_system,
    _metrics,
    transform_linear_coefficients_to_charmm,
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stage", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--initial-fit", type=Path)
    args = p.parse_args()
    old, root = args.stage.resolve(), args.output.resolve()
    root.mkdir(exist_ok=False)
    (root / "fit_snapshot.py").write_text(Path(__file__).read_text())
    # Freeze one prospective objective before solving; no weight search or
    # validation-based reselection. Existing tolerances remain unchanged.
    policy = json.loads((old / "policy.json").read_text())
    policy["equilibrium_objective"] = {
        "minimum_gradient_weight_multiplier": 10.0,
        "ridge_lambda": 0.0001,
        "rationale": "Keep the existing 10x minimum-gradient objective and all displaced targets, but impose both C6-H6 directional gradient and curvature values from the audited TRAINING minimum as four equality constraints. The independent stretch scan motivates testing local constraints but supplies no fitted target values. No validation selection or release.",
        "selection": "One fixed candidate; validation evaluation only; no weight search.",
        "source_campaign": source(
            old / "response_campaign/response_campaign_manifest.json"
        ),
        "source_physical_policy": source(old / "fit_policy.json"),
        "code": source(root / "fit_snapshot.py"),
        "initial_fit": source(args.initial_fit) if args.initial_fit else None,
    }
    write(root / "policy.json", policy)
    for name in ("basis", "responses", "bonded_fit_plan.json"):
        (root / name).symlink_to(old / name)
    campaign, training, validation = _campaign(
        old / "response_campaign/response_campaign_manifest.json"
    )
    rank = campaign["training_identifiability"]["joint_normalized_diagnostic_block"]
    if rank["nullity"] != 0:
        raise ValueError("Source training design is not identifiable")
    spec = json.loads((old / "quantitative_fit_specification.json").read_text())
    physical = json.loads((old / "fit_policy.json").read_text())
    prior = json.loads(
        (args.initial_fit or old / "selected_response_fit.json").read_text()
    )
    params = spec["parameters"]
    if args.initial_fit:
        # Warm-start only: duplicate the former shared H6 bond coefficients.
        # Every other chemical group/basis identity must match exactly.
        def identity(record, allow_endpoint=False):
            group = record["group_id"]
            if allow_endpoint and group in {
                "bonds:drude-hydrogen-C6-H6-endpoint1",
                "bonds:drude-hydrogen-C6-H6-endpoint2",
            }:
                group = "bonds:drude-hydrogen-C6-H6"
            return (
                group,
                record["basis"],
                record.get("periodicity"),
                record.get("reference_degrees"),
            )

        lookup = {identity(r): r["coefficient"] for r in prior["parameters"]}
        if len(lookup) != len(prior["parameters"]):
            raise ValueError("Ambiguous initial parameter identities")
        initial = np.array(
            [
                lookup[identity(r)]
                if identity(r) in lookup
                else lookup[identity(r, True)]
                for r in params
            ]
        )
        write(
            root / "initial_coefficients.json",
            {
                "role": "warm start only, not fitted endpoint parameters",
                "source": source(args.initial_fit),
                "parameters": [
                    {**r, "coefficient": float(c)} for r, c in zip(params, initial)
                ],
            },
        )
    elif [r["name"] for r in params] != [r["name"] for r in prior["parameters"]]:
        raise ValueError("Parameter order mismatch")
    else:
        initial = np.array([r["coefficient"] for r in prior["parameters"]])
    scales = np.array([r["scale"] for r in params])
    lower = np.array([r["lower_bound"] for r in params]) / scales
    upper = np.array([r["upper_bound"] for r in params]) / scales
    lower, upper, constraint, _ = _physical_equilibrium_constraint_system(
        params, scales, lower, upper, physical
    )
    a, b = _weighted_system(training, spec["objective"])
    # Identify the audited minimum by source kind, not positional coincidence.
    minima = [
        d
        for d in training
        if json.loads(d["manifest_path"].read_text())["target"]["kind"]
        == "audited_harmonic_minimum"
    ]
    if len(minima) != 1:
        raise ValueError("Expected one audited training minimum")
    minimum = minima[0]["arrays"]
    factor = np.sqrt(
        9.0
        * spec["objective"]["gradient_weight"]
        / len(minimum["projected_residual_gradient"])
    )
    a = np.vstack([a, factor * minimum["projected_design_gradient"]]) * scales
    b = np.concatenate([b, factor * minimum["projected_residual_gradient"]])
    ridge = 0.0001
    manifest_path = old / "responses/minimum/linear_response_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    with np.load(checked(manifest["outputs"]["linear_response_arrays"])) as loaded:
        arrays = dict(loaded)
    atom_map = json.loads(checked(manifest["sources"]["stable_atom_map"]).read_text())
    idx = {row["stable_atom_key"]: i for i, row in enumerate(atom_map)}
    xyz = np.array(
        [
            row[1:]
            for row in parse_xyz(
                checked(manifest["sources"]["target_geometry"]).read_text()
            )[0]
        ]
    )
    eq_rows, eq_targets, descriptions = [], [], []
    for endpoint in (1, 2):
        ci, hi = idx[f"{endpoint}:C6"], idx[f"{endpoint}:H6"]
        axis = xyz[hi] - xyz[ci]
        axis /= np.linalg.norm(axis)
        mc, mh = arrays["masses_amu"][[ci, hi]]
        direction = np.zeros_like(xyz)
        direction[hi] = axis * mc / (mc + mh)
        direction[ci] = -axis * mh / (mc + mh)
        q = direction.ravel()
        for kind in ("gradient", "curvature"):
            if kind == "gradient":
                row = arrays["parameter_gradient_response"] @ q
                base = float(arrays["base_gradient_kcal_mol_angstrom"] @ q)
                target = float(arrays["qm_gradient_kcal_mol_angstrom"] @ q)
            else:
                row = np.einsum(
                    "i,pij,j->p", q, arrays["parameter_hessian_response"], q
                )
                base = float(q @ arrays["base_hessian_kcal_mol_angstrom2"] @ q)
                target = float(q @ arrays["qm_hessian_kcal_mol_angstrom2"] @ q)
            norm = np.linalg.norm(row * scales)
            eq_rows.append(row * scales / norm)
            eq_targets.append((target - base) / norm)
            descriptions.append(
                {
                    "endpoint": endpoint,
                    "kind": kind,
                    "qm_value": target,
                    "fixed_value": base,
                    "normalization": norm,
                }
            )
    eq_matrix, eq_rhs = np.array(eq_rows), np.array(eq_targets)
    write(
        root / "minimum_constraints.json",
        {
            "source": source(manifest_path),
            "records": descriptions,
            "matrix": eq_matrix.tolist(),
            "rhs": eq_rhs.tolist(),
            "simulation_ready": False,
        },
    )
    normal = a.T @ a + ridge * np.eye(len(scales))
    rhs = a.T @ b
    start = initial / scales
    fit = minimize(
        lambda x: 0.5 * float(np.linalg.norm(a @ x - b) ** 2 + ridge * (x @ x)),
        start,
        jac=lambda x: normal @ x - rhs,
        method="SLSQP",
        bounds=list(zip(lower, upper)),
        constraints=[
            LinearConstraint(*constraint),
            LinearConstraint(eq_matrix, eq_rhs, eq_rhs),
        ],
        options={"ftol": 1e-12, "maxiter": 2000},
    )
    violation = max(
        float(abs(eq_matrix @ fit.x - eq_rhs).max()),
        float(np.max(np.maximum(constraint[1] - constraint[0] @ fit.x, 0))),
        float(np.max(np.maximum(constraint[0] @ fit.x - constraint[2], 0))),
        float(np.max(np.maximum(lower - fit.x, 0))),
        float(np.max(np.maximum(fit.x - upper, 0))),
    )
    write(
        root / "solver.json",
        {
            "success": bool(fit.success),
            "message": str(fit.message),
            "iterations": int(fit.nit),
            "maximum_constraint_violation": violation,
            "minimum_constraint_residuals_physical_units": [
                float(v * r["normalization"])
                for v, r in zip(eq_matrix @ fit.x - eq_rhs, descriptions)
            ],
        },
    )
    if not fit.success or violation > 1e-8 or not np.all(np.isfinite(fit.x)):
        raise ValueError("Constrained diagnostic fit failed")
    coefficients = fit.x * scales
    records = [{**r, "coefficient": float(c)} for r, c in zip(params, coefficients)]
    transformed = transform_linear_coefficients_to_charmm(records)
    write(
        root / "charmm_bonded_transform.json",
        {
            "schema": "nadoc.isolated-charmm-transform-diagnostic.v1",
            "simulation_ready": False,
            "gate_effect": "none",
            "terms": transformed,
        },
    )
    write(
        root / "selected_response_fit.json",
        {
            "schema": "nadoc.isolated-equilibrium-fit-diagnostic.v1",
            "status": "fixed_prospective_candidate_not_release_selected",
            "simulation_ready": False,
            "gate_effect": "none",
            "parameters": records,
            "ridge_lambda": ridge,
            "policy": source(root / "policy.json"),
            "training_metrics": _metrics(training, coefficients),
            "validation_metrics": _metrics(validation, coefficients),
            "prior_training_metrics": _metrics(training, start * scales),
            "prior_validation_metrics": _metrics(validation, start * scales),
        },
    )
    print(
        "Prospective fit complete; requires geometry, Hessian and independent validation."
    )


if __name__ == "__main__":
    main()
