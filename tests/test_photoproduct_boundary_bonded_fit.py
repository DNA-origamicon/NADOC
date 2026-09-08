import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

import backend.parameterization.photoproduct_boundary_bonded_fit as module
from backend.parameterization.photoproduct_boundary_bonded_fit import (
    fit_boundary_bonded_response,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_boundary_bonded_row_holdout_selects_a_physical_fixed_improper_fit(
    tmp_path: Path, monkeypatch
):
    fit_plan = tmp_path / "fit_plan.json"
    fit_plan.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-bonded-fit-plan.v1",
                "status": "candidate_plan_unassigned_not_releasable",
                "product_id": "tt-cpd-trans-anti-i",
                "model_id": "full-boundary-test",
                "hypothesis_id": "charmm36-hybrid-cyclobutane-v1",
            }
        )
        + "\n"
    )
    basis = tmp_path / "basis.json"
    basis.write_text(
        json.dumps(
            {
                "improper_equilibrium_mode": "fixed_qm_reference",
                "angle_urey_bradley_mode": "omit",
                "sources": {
                    "fit_plan": {
                        "path": str(fit_plan),
                        "sha256": _sha256(fit_plan),
                    }
                },
            }
        )
        + "\n"
    )
    response_path = tmp_path / "response.json"
    response_path.write_text("{}\n")
    parameters = [
        {
            "name": "bond-r2",
            "group_id": "bonds:test",
            "category": "bonds",
            "basis": "r^2",
            "coefficient_units": "kcal/mol/angstrom^2",
            "occurrence_count": 1,
        },
        {
            "name": "bond-r",
            "group_id": "bonds:test",
            "category": "bonds",
            "basis": "r",
            "coefficient_units": "kcal/mol/angstrom",
            "occurrence_count": 1,
        },
    ]
    for periodicity in range(1, 7):
        parameters.append(
            {
                "name": f"dihedral-{periodicity}",
                "group_id": "dihedrals:test",
                "category": "dihedrals",
                "basis": f"cos({periodicity}*phi)",
                "coefficient_units": "kcal/mol",
                "periodicity": periodicity,
                "occurrence_count": 1,
            }
        )
    expected = ("positive", "negative", "positive", "negative")
    for index, sign in enumerate(expected):
        parameters.append(
            {
                "name": f"improper-{index}",
                "group_id": f"improper:{index}",
                "category": "impropers",
                "basis": "wrapped_delta^2",
                "coefficient_units": "kcal/mol/rad^2",
                "occurrence_count": 1,
                "ordered_atoms_candidate": [f"a{index}", "b", "c", "d"],
                "reference_degrees": 20.0 if sign == "positive" else -20.0,
                "expected_signed_volume": sign,
            }
        )
    generator = np.random.default_rng(7)
    gradient_design = generator.normal(size=(50, len(parameters)))
    hessian_design = generator.normal(size=(100, len(parameters)))
    true_coefficients = np.asarray(
        [100.0, -300.0, 0.2, -0.3, 0.4, -0.5, 0.6, -0.7, 10.0, 12.0, 14.0, 16.0]
    )
    arrays = {
        "projected_design_gradient": gradient_design,
        "projected_residual_gradient": gradient_design @ true_coefficients,
        "projected_design_hessian_upper": hessian_design,
        "projected_residual_hessian_upper": hessian_design @ true_coefficients,
    }
    response = {
        "product_id": "tt-cpd-trans-anti-i",
        "model_id": "full-boundary-test",
        "hypothesis_id": "charmm36-hybrid-cyclobutane-v1",
        "atom_count": 63,
        "cartesian_dimension": 189,
        "sources": {
            "fit_basis_manifest": {
                "path": str(basis),
                "sha256": _sha256(basis),
            }
        },
    }
    monkeypatch.setattr(
        module,
        "_load_response",
        lambda _path: {
            "response": response,
            "parameters": parameters,
            "arrays": arrays,
        },
    )

    report = fit_boundary_bonded_response(
        response_manifest_path=response_path,
        fit_plan_path=fit_plan,
        output_dir=tmp_path / "fit",
    )

    assert report["status"] == "physical_candidate_selected_for_engine_smoke"
    selected = json.loads(
        (tmp_path / "fit/selected_response_fit.json").read_text()
    )
    transform = json.loads(
        (tmp_path / "fit/charmm_bonded_transform.json").read_text()
    )
    assert all(
        item["passed"] for item in selected["selection_checks"].values()
    )
    assert transform["bonded_terms"]["bonds"][0]["r0_angstrom"] == pytest.approx(
        1.5, abs=0.05
    )
    assert [
        "positive" if item["psi0_degrees"] > 0 else "negative"
        for item in transform["bonded_terms"]["impropers"]
    ] == list(expected)
