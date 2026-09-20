"""Test joint training-minimum force and H6-curvature feasibility, without refit."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import linprog

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write
from backend.parameterization.photoproduct_response_fit import (
    _campaign,
    _physical_equilibrium_constraint_system,
)


def main(stage, constrained, root):
    root.mkdir(exist_ok=False)
    (root / "source_snapshot.py").write_text(Path(__file__).read_text())
    manifest_path = stage / "response_campaign/response_campaign_manifest.json"
    _, training, _ = _campaign(manifest_path)
    minimum = next(
        d["arrays"]
        for d in training
        if json.loads(d["manifest_path"].read_text())["target"]["kind"]
        == "audited_harmonic_minimum"
    )
    spec = json.loads((stage / "quantitative_fit_specification.json").read_text())
    params = spec["parameters"]
    scales = np.array([p["scale"] for p in params])
    physical = json.loads((stage / "fit_policy.json").read_text())
    lower = np.array([p["lower_bound"] for p in params]) / scales
    upper = np.array([p["upper_bound"] for p in params]) / scales
    lower, upper, constraint, _ = _physical_equilibrium_constraint_system(
        params, scales, lower, upper, physical
    )
    h6 = json.loads((constrained / "minimum_constraints.json").read_text())
    checked(h6["source"])
    gradient_a = minimum["projected_design_gradient"] * scales
    gradient_b = minimum["projected_residual_gradient"]
    original_a = np.vstack([gradient_a, np.array(h6["matrix"])[[1, 3]]])
    original_b = np.concatenate([gradient_b, np.array(h6["rhs"])[[1, 3]]])
    norms = np.linalg.norm(original_a, axis=1)
    norms[norms == 0] = 1
    a = original_a / norms[:, None]
    b = original_b / norms
    u, singular, vh = np.linalg.svd(a, full_matrices=False)
    rank = int(np.sum(singular > singular[0] * 1e-10))
    projection = u[:, :rank] @ (u[:, :rank].T @ b)
    incompatible = float(abs(b - projection).max())
    independent_a = vh[:rank]
    independent_b = (u[:, :rank].T @ b) / singular[:rank]
    c, lo, hi = constraint
    inequalities, targets = [], []
    for row, low, high in zip(c, lo, hi):
        if np.isfinite(high):
            inequalities.append(row)
            targets.append(high)
        if np.isfinite(low):
            inequalities.append(-row)
            targets.append(-low)
    result = linprog(
        np.zeros(len(params)),
        A_ub=np.array(inequalities),
        b_ub=np.array(targets),
        A_eq=independent_a,
        b_eq=independent_b,
        bounds=list(zip(lower, upper)),
        method="highs",
    )
    report = {
        "simulation_ready": False,
        "gate_effect": "none",
        "scope": "Training-only linear feasibility of full projected reference gradient plus both H6 curvature equalities. Feasible coefficients are a witness, not a fitted or validated force field.",
        "sources": [
            source(p)
            for p in (
                manifest_path,
                stage / "quantitative_fit_specification.json",
                stage / "fit_policy.json",
                constrained / "minimum_constraints.json",
                root / "source_snapshot.py",
            )
        ],
        "parameter_count": len(params),
        "equations": len(b),
        "rank_relative_threshold": 1e-10,
        "rank": rank,
        "normalized_left_null_residual_max": incompatible,
        "linear_program_success": bool(result.success),
        "linear_program_status": int(result.status),
        "linear_program_message": str(result.message),
        "joint_feasible": bool(result.success and incompatible <= 1e-8),
    }
    gradient_only = []
    for cutoff in (1e-8, 1e-10, 1e-12):
        coefficients, _, gradient_rank, sv = np.linalg.lstsq(
            gradient_a, gradient_b, rcond=cutoff
        )
        residual = gradient_a @ coefficients - gradient_b
        response_manifest = json.loads(
            (stage / "responses/minimum/linear_response_manifest.json").read_text()
        )
        with np.load(
            checked(response_manifest["outputs"]["linear_response_arrays"])
        ) as loaded:
            masses = loaded["masses_amu"]
        atom_map = json.loads(
            checked(response_manifest["sources"]["stable_atom_map"]).read_text()
        )
        cartesian_residual = (residual * np.repeat(np.sqrt(masses), 3)).reshape(-1, 3)
        atom_errors = np.linalg.norm(cartesian_residual, axis=1)
        gradient_only.append(
            {
                "svd_relative_cutoff": cutoff,
                "rank": int(gradient_rank),
                "mass_weighted_projected_residual_rms": float(
                    np.sqrt(np.mean(residual**2))
                ),
                "projected_cartesian_residual_max_component_kcal_mol_angstrom": float(
                    abs(cartesian_residual).max()
                ),
                "largest_atom_residuals": [
                    {
                        "atom": atom_map[i]["stable_atom_key"],
                        "norm_kcal_mol_angstrom": float(atom_errors[i]),
                    }
                    for i in np.argsort(atom_errors)[-8:][::-1]
                ],
            }
        )
    report["unbounded_gradient_only_least_squares"] = gradient_only
    report["gradient_only_scope"] = (
        "Lower bound without parameter bounds or curvature constraints; projected mass-weighted residual mapped back by sqrt(mass), not an accepted coefficient set."
    )
    if result.success:
        full_residual = original_a @ result.x - original_b
        report["projected_gradient_residual_max"] = float(abs(full_residual[:-2]).max())
        report["normalized_h6_curvature_residual_max"] = float(
            abs(full_residual[-2:]).max()
        )
        write(
            root / "feasibility_witness.json",
            {
                "simulation_ready": False,
                "role": "Feasibility witness only; not for simulation",
                "parameters": [
                    {**p, "coefficient": float(v)}
                    for p, v in zip(params, result.x * scales)
                ],
            },
        )
    write(root / "assessment.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for name in ("stage", "constrained", "root"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    main(a.stage.resolve(), a.constrained.resolve(), a.root.resolve())
