"""Training/holdout assembly for independent photoproduct response evidence."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

from backend.parameterization.photoproduct_response_campaign import (
    build_openmm_response_campaign,
)
from backend.parameterization.photoproduct_response_fit import (
    build_charmm_bonded_transform_candidate,
    build_response_fit_selection_template,
    build_response_fit_specification_template,
    compare_response_fit_evaluations,
    evaluate_reviewed_response_fit,
    extract_reviewed_response_fit_candidate,
    materialize_quantitative_response_fit_specification,
    select_quantitative_response_fit_candidate,
    transform_linear_coefficients_to_charmm,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _response_fixture(
    root: Path,
    *,
    dataset: str,
    gradient: np.ndarray,
    parameter_map: Path,
    stable_map: Path,
    reviewed_partition: str | None = None,
    hypothesis_id: str = "shared-cyclobutane-carbon-v1",
) -> Path:
    directory = root / dataset
    directory.mkdir()
    hessian_targets = directory / "hessian_targets.json"
    hessian_targets.write_text(
        json.dumps(
            (
                {
                    "schema": "nadoc.photoproduct-hessian-target-bundle.v2",
                    "status": "candidate_off_equilibrium_response_evidence",
                    "simulation_ready": False,
                    "gate_effect": "none",
                    "target_kind": "reviewed_off_equilibrium_conformer",
                    "partition": reviewed_partition,
                    "product_id": f"tt-cpd-{dataset}",
                    "model_id": "n-methyl-dimer",
                }
                if reviewed_partition is not None
                else {
                    "schema": "nadoc.photoproduct-hessian-target-bundle.v1",
                    "frequency_evidence_status": "passed_harmonic_minimum",
                    "gate_effect": "none",
                    "product_id": f"tt-cpd-{dataset}",
                    "model_id": "n-methyl-dimer",
                }
            )
        )
        + "\n"
    )
    arrays = directory / "response.npz"
    gradient = np.asarray(gradient, dtype=float)
    hessian = gradient * 2.0
    np.savez_compressed(
        arrays,
        projected_design_gradient=gradient,
        projected_residual_gradient=np.arange(gradient.shape[0], dtype=float) + 1.0,
        projected_design_hessian_upper=hessian,
        projected_residual_hessian_upper=np.arange(hessian.shape[0], dtype=float) + 1.0,
    )
    manifest = directory / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-openmm-linear-response.v1",
                "status": "candidate_response_unfitted_not_releasable",
                "simulation_ready": False,
                "gate_effect": "none",
                "product_id": f"tt-cpd-{dataset}",
                "model_id": "n-methyl-dimer",
                "hypothesis_id": hypothesis_id,
                "parameter_count": 3,
                "outputs": {
                    "linear_response_arrays": {
                        "path": str(arrays),
                        "sha256": _sha256(arrays),
                    }
                },
                "sources": {
                    "linear_parameter_map": {
                        "path": str(parameter_map),
                        "sha256": _sha256(parameter_map),
                    },
                    "stable_atom_map": {
                        "path": str(stable_map),
                        "sha256": _sha256(stable_map),
                    },
                    "hessian_targets": {
                        "path": str(hessian_targets),
                        "sha256": _sha256(hessian_targets),
                    },
                },
            }
        )
        + "\n"
    )
    return manifest


def _fixtures(
    tmp_path: Path, hypothesis_id: str = "shared-cyclobutane-carbon-v1"
) -> tuple[Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    parameter_map = tmp_path / "parameters.json"
    parameter_map.write_text(
        json.dumps(
            [
                {
                    "name": "a",
                    "group_id": "dihedral:a",
                    "category": "dihedrals",
                    "basis": "cos(1*phi)",
                    "coefficient_units": "kcal/mol",
                    "periodicity": 1,
                    "occurrence_count": 1,
                },
                {
                    "name": "b",
                    "group_id": "dihedral:b",
                    "category": "dihedrals",
                    "basis": "cos(2*phi)",
                    "coefficient_units": "kcal/mol",
                    "periodicity": 2,
                    "occurrence_count": 1,
                },
                {
                    "name": "c",
                    "group_id": "dihedral:c",
                    "category": "dihedrals",
                    "basis": "cos(3*phi)",
                    "coefficient_units": "kcal/mol",
                    "periodicity": 3,
                    "occurrence_count": 1,
                },
            ]
        )
        + "\n"
    )
    stable_map = tmp_path / "stable_map.json"
    stable_map.write_text(json.dumps(["A", "B", "C"]) + "\n")
    first = _response_fixture(
        tmp_path,
        dataset="cis-syn",
        gradient=np.asarray([[1.0, 0.0, 0.0]]),
        parameter_map=parameter_map,
        stable_map=stable_map,
        hypothesis_id=hypothesis_id,
    )
    second = _response_fixture(
        tmp_path,
        dataset="trans-syn-i",
        gradient=np.asarray([[0.0, 1.0, 0.0]]),
        parameter_map=parameter_map,
        stable_map=stable_map,
        hypothesis_id=hypothesis_id,
    )
    holdout = _response_fixture(
        tmp_path,
        dataset="cis-anti-i",
        gradient=np.asarray([[0.0, 0.0, 1.0]]),
        parameter_map=parameter_map,
        stable_map=stable_map,
        hypothesis_id=hypothesis_id,
    )
    return first, second, holdout


def test_campaign_keeps_holdout_disjoint_and_reports_rank_gain(tmp_path: Path) -> None:
    first, second, holdout = _fixtures(tmp_path)
    output = tmp_path / "campaign"

    manifest = build_openmm_response_campaign(
        training_response_paths=[first, second],
        validation_response_paths=[holdout],
        output_dir=output,
    )

    assert manifest["gate_effect"] == "none"
    assert manifest["simulation_ready"] is False
    assert manifest["partitions_disjoint"] is True
    assert manifest["training_dataset_count"] == 2
    assert manifest["validation_dataset_count"] == 1
    assert [item["rank_gain"] for item in manifest["training_rank_progression"]] == [
        1,
        1,
    ]
    assert (
        manifest["training_identifiability"]["joint_normalized_diagnostic_block"][
            "nullity"
        ]
        == 1
    )
    arrays_path = Path(manifest["outputs"]["training_response_arrays"]["path"])
    with np.load(arrays_path, allow_pickle=False) as arrays:
        assert arrays["projected_design_gradient"].shape == (2, 3)
        assert arrays["projected_residual_gradient"].shape == (2,)
        assert arrays["gradient_row_offsets"].tolist() == [0, 1, 2]
    persisted = json.loads((output / "response_campaign_manifest.json").read_text())
    assert persisted == manifest
    assert persisted["validation_datasets"][0]["partition"] == "validation"
    assert "cis-anti-i" in persisted["validation_datasets"][0]["dataset_id"]


def test_campaign_rejects_overlap_hash_mismatch_and_overwrite(tmp_path: Path) -> None:
    first, second, holdout = _fixtures(tmp_path)
    with pytest.raises(ValueError, match="disjoint"):
        build_openmm_response_campaign(
            training_response_paths=[first, second],
            validation_response_paths=[first],
            output_dir=tmp_path / "overlap",
        )

    payload = json.loads(holdout.read_text())
    payload["outputs"]["linear_response_arrays"]["sha256"] = "0" * 64
    holdout.write_text(json.dumps(payload) + "\n")
    with pytest.raises(ValueError, match="hash-mismatched"):
        build_openmm_response_campaign(
            training_response_paths=[first, second],
            validation_response_paths=[holdout],
            output_dir=tmp_path / "bad-hash",
        )

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError, match="overwrite"):
        build_openmm_response_campaign(
            training_response_paths=[first],
            validation_response_paths=[second],
            output_dir=existing,
        )


def test_campaign_rejects_parameter_or_atom_identity_drift(tmp_path: Path) -> None:
    first, second, holdout = _fixtures(tmp_path)
    alternate_parameters = tmp_path / "alternate_parameters.json"
    alternate_parameters.write_text(
        json.dumps(
            [
                {"name": "x", "group_id": "dihedral:x", "category": "dihedrals"},
                {"name": "b", "group_id": "dihedral:b", "category": "dihedrals"},
                {"name": "c", "group_id": "dihedral:c", "category": "dihedrals"},
            ]
        )
        + "\n"
    )
    payload = json.loads(second.read_text())
    payload["sources"]["linear_parameter_map"] = {
        "path": str(alternate_parameters),
        "sha256": _sha256(alternate_parameters),
    }
    second.write_text(json.dumps(payload) + "\n")
    with pytest.raises(ValueError, match="exact same parameter map"):
        build_openmm_response_campaign(
            training_response_paths=[first, second],
            validation_response_paths=[holdout],
            output_dir=tmp_path / "parameter-drift",
        )

    first, second, holdout = _fixtures(tmp_path / "atom-case")
    alternate_map = tmp_path / "atom-case" / "alternate_map.json"
    alternate_map.write_text(json.dumps(["A", "C", "B"]) + "\n")
    payload = json.loads(second.read_text())
    payload["sources"]["stable_atom_map"] = {
        "path": str(alternate_map),
        "sha256": _sha256(alternate_map),
    }
    second.write_text(json.dumps(payload) + "\n")
    with pytest.raises(ValueError, match="exact same stable atom map"):
        build_openmm_response_campaign(
            training_response_paths=[first, second],
            validation_response_paths=[holdout],
            output_dir=tmp_path / "atom-drift",
        )


def test_campaign_enforces_human_reviewed_conformer_partitions(
    tmp_path: Path,
) -> None:
    parameter_map = tmp_path / "parameters.json"
    parameter_map.write_text(
        json.dumps(
            [
                {"name": "a", "group_id": "dihedral:a", "category": "dihedrals"},
                {"name": "b", "group_id": "dihedral:b", "category": "dihedrals"},
                {"name": "c", "group_id": "dihedral:c", "category": "dihedrals"},
            ]
        )
        + "\n"
    )
    stable_map = tmp_path / "stable_map.json"
    stable_map.write_text(json.dumps(["A", "B", "C"]) + "\n")
    training = _response_fixture(
        tmp_path,
        dataset="reviewed-training",
        gradient=np.asarray([[1.0, 0.0, 0.0]]),
        parameter_map=parameter_map,
        stable_map=stable_map,
        reviewed_partition="training",
    )
    validation = _response_fixture(
        tmp_path,
        dataset="reviewed-validation",
        gradient=np.asarray([[0.0, 1.0, 0.0]]),
        parameter_map=parameter_map,
        stable_map=stable_map,
        reviewed_partition="validation",
    )

    with pytest.raises(ValueError, match="reviewed conformer partition differs"):
        build_openmm_response_campaign(
            training_response_paths=[validation],
            validation_response_paths=[training],
            output_dir=tmp_path / "leaked-partitions",
        )


def test_reviewed_bounded_ridge_grid_reports_holdout_without_selecting(
    tmp_path: Path,
) -> None:
    first, second, holdout = _fixtures(tmp_path)
    campaign_dir = tmp_path / "campaign"
    build_openmm_response_campaign(
        training_response_paths=[first, second],
        validation_response_paths=[holdout],
        output_dir=campaign_dir,
    )
    campaign_path = campaign_dir / "response_campaign_manifest.json"
    specification_path = tmp_path / "fit_specification.json"
    template = build_response_fit_specification_template(
        campaign_path=campaign_path,
        output_path=specification_path,
    )
    assert template["status"] == "review_required"
    assert template["selection"] is None
    with pytest.raises(ValueError, match="human review"):
        evaluate_reviewed_response_fit(
            campaign_path=campaign_path,
            specification_path=specification_path,
            output_dir=tmp_path / "must-not-exist",
        )

    template.update(
        {
            "status": "reviewed",
            "reviewed_by": "Qualified Test Reviewer",
            "reviewed_at": "2026-09-04T22:00:00Z",
            "review_rationale": (
                "Synthetic bounds, scaling, and weights exercise the non-selecting "
                "training and independent holdout evaluation boundary."
            ),
        }
    )
    template["objective"] = {
        "dataset_weighting": "equal_dataset_rms",
        "gradient_weight": 1.0,
        "hessian_weight": 0.25,
        "ridge_lambdas": [0.0, 0.1, 1.0],
    }
    for parameter in template["parameters"]:
        parameter["scale"] = 2.0
        parameter["lower_bound"] = -5.0
        parameter["upper_bound"] = 5.0
    specification_path.write_text(json.dumps(template, indent=2) + "\n")

    output = tmp_path / "evaluation"
    report = evaluate_reviewed_response_fit(
        campaign_path=campaign_path,
        specification_path=specification_path,
        output_dir=output,
    )
    assert report["status"] == "candidate_fits_evaluated_human_selection_required"
    assert report["simulation_ready"] is False
    assert report["gate_effect"] == "none"
    assert report["selection"] is None
    assert report["candidate_count"] == 3
    assert report["software"]["solver"] == "scipy.optimize.lsq_linear"
    assert report["software"]["numpy"]
    assert report["software"]["scipy"]
    assert all(
        item["validation"]["dataset_count"] == 1 for item in report["candidates"]
    )
    arrays_path = Path(report["outputs"]["candidate_coefficients"]["path"])
    with np.load(arrays_path, allow_pickle=False) as arrays:
        assert arrays["coefficients"].shape == (3, 3)
        assert arrays["ridge_lambdas"].tolist() == [0.0, 0.1, 1.0]
    assert json.loads((output / "response_fit_evaluation.json").read_text()) == report


def test_quantitative_fit_spec_uses_training_only_and_is_hash_pinned(
    tmp_path: Path,
) -> None:
    first, second, holdout = _fixtures(tmp_path)
    campaign_dir = tmp_path / "campaign"
    build_openmm_response_campaign(
        training_response_paths=[first, second],
        validation_response_paths=[holdout],
        output_dir=campaign_dir,
    )
    campaign_path = campaign_dir / "response_campaign_manifest.json"
    spec_path = tmp_path / "quantitative-spec.json"
    spec = materialize_quantitative_response_fit_specification(
        campaign_path=campaign_path,
        output_path=spec_path,
    )
    assert spec["status"] == "quantitatively_specified"
    assert spec["quantitative_specification"]["releases_parameters"] is False
    assert spec["objective"]["gradient_weight"] == pytest.approx(1.0)
    assert spec["objective"]["hessian_weight"] == pytest.approx(1.0)
    assert all(item["lower_bound"] == -20.0 for item in spec["parameters"])
    report = evaluate_reviewed_response_fit(
        campaign_path=campaign_path,
        specification_path=spec_path,
        output_dir=tmp_path / "quantitative-evaluation",
    )
    assert report["candidate_count"] == 7
    policy_path = Path(spec["quantitative_specification"]["policy_source"]["path"])
    changed = json.loads(policy_path.read_text())
    changed["ridge_lambdas"] = [0.0, 1.0]
    stale_policy = tmp_path / "stale-policy.json"
    stale_policy.write_text(json.dumps(changed))
    stale = json.loads(spec_path.read_text())
    stale["quantitative_specification"]["policy_source"] = {
        "path": str(stale_policy),
        "sha256": _sha256(stale_policy),
    }
    spec_path.write_text(json.dumps(stale))
    with pytest.raises(ValueError, match="human review"):
        evaluate_reviewed_response_fit(
            campaign_path=campaign_path,
            specification_path=spec_path,
            output_dir=tmp_path / "stale-must-not-exist",
        )


def test_quantitative_fit_selection_requires_full_rank_and_transforms(
    tmp_path: Path,
) -> None:
    first, second, third = _fixtures(tmp_path)
    first_payload = json.loads(first.read_text())
    parameter_map = Path(first_payload["sources"]["linear_parameter_map"]["path"])
    stable_map = Path(first_payload["sources"]["stable_atom_map"]["path"])
    holdout = _response_fixture(
        tmp_path,
        dataset="independent-holdout",
        gradient=np.asarray([[1.0, 1.0, 1.0]]),
        parameter_map=parameter_map,
        stable_map=stable_map,
    )
    campaign_dir = tmp_path / "full-rank-campaign"
    build_openmm_response_campaign(
        training_response_paths=[first, second, third],
        validation_response_paths=[holdout],
        output_dir=campaign_dir,
    )
    campaign_path = campaign_dir / "response_campaign_manifest.json"
    assert json.loads(campaign_path.read_text())["status"] == (
        "training_design_full_rank_diagnostic_only"
    )
    spec_path = tmp_path / "quantitative-spec.json"
    materialize_quantitative_response_fit_specification(
        campaign_path=campaign_path,
        output_path=spec_path,
    )
    evaluation_dir = tmp_path / "evaluation"
    evaluate_reviewed_response_fit(
        campaign_path=campaign_path,
        specification_path=spec_path,
        output_dir=evaluation_dir,
    )
    selected_path = tmp_path / "selected.json"
    selected = select_quantitative_response_fit_candidate(
        evaluation_path=evaluation_dir / "response_fit_evaluation.json",
        output_path=selected_path,
    )
    assert selected["status"].startswith("quantitatively_selected")
    assert selected["decision_authority"]["releases_parameters"] is False
    transformed = build_charmm_bonded_transform_candidate(
        selected_candidate_path=selected_path,
        output_path=tmp_path / "transformed.json",
    )
    assert transformed["selection_authority"] == "automated_quantitative_policy"
    assert transformed["simulation_ready"] is False


def test_response_fit_specification_rejects_selection_and_missing_bounds(
    tmp_path: Path,
) -> None:
    first, second, holdout = _fixtures(tmp_path)
    campaign_dir = tmp_path / "campaign"
    build_openmm_response_campaign(
        training_response_paths=[first, second],
        validation_response_paths=[holdout],
        output_dir=campaign_dir,
    )
    campaign_path = campaign_dir / "response_campaign_manifest.json"
    specification_path = tmp_path / "fit_specification.json"
    spec = build_response_fit_specification_template(
        campaign_path=campaign_path,
        output_path=specification_path,
    )
    spec.update(
        {
            "status": "reviewed",
            "reviewed_by": "Qualified Test Reviewer",
            "reviewed_at": "2026-09-04T22:00:00Z",
            "review_rationale": "This is a sufficiently detailed synthetic review rationale.",
            "selection": {"ridge_lambda": 0.1},
        }
    )
    spec["objective"] = {
        "dataset_weighting": "raw_rows",
        "gradient_weight": 1.0,
        "hessian_weight": 1.0,
        "ridge_lambdas": [0.0, 0.1],
    }
    specification_path.write_text(json.dumps(spec, indent=2) + "\n")
    with pytest.raises(ValueError, match="non-selecting human review"):
        evaluate_reviewed_response_fit(
            campaign_path=campaign_path,
            specification_path=specification_path,
            output_dir=tmp_path / "selected",
        )

    spec["selection"] = None
    specification_path.write_text(json.dumps(spec, indent=2) + "\n")
    with pytest.raises(ValueError, match="scale and bounds"):
        evaluate_reviewed_response_fit(
            campaign_path=campaign_path,
            specification_path=specification_path,
            output_dir=tmp_path / "unbounded",
        )

    spec["parameters"][0]["group_id"] = "misleading:replacement-group"
    specification_path.write_text(json.dumps(spec, indent=2) + "\n")
    with pytest.raises(ValueError, match="identity/order differs"):
        evaluate_reviewed_response_fit(
            campaign_path=campaign_path,
            specification_path=specification_path,
            output_dir=tmp_path / "identity-drift",
        )


def _fit_evaluation(root: Path, hypothesis_id: str) -> Path:
    first, second, holdout = _fixtures(root, hypothesis_id)
    campaign_dir = root / "campaign"
    build_openmm_response_campaign(
        training_response_paths=[first, second],
        validation_response_paths=[holdout],
        output_dir=campaign_dir,
    )
    campaign_path = campaign_dir / "response_campaign_manifest.json"
    specification_path = root / "fit_specification.json"
    spec = build_response_fit_specification_template(
        campaign_path=campaign_path,
        output_path=specification_path,
    )
    spec.update(
        {
            "status": "reviewed",
            "reviewed_by": "Qualified Test Reviewer",
            "reviewed_at": "2026-09-04T22:00:00Z",
            "review_rationale": (
                "Synthetic review supplies explicit like-for-like model comparison settings."
            ),
        }
    )
    spec["objective"] = {
        "dataset_weighting": "equal_dataset_rms",
        "gradient_weight": 1.0,
        "hessian_weight": 0.25,
        "ridge_lambdas": [0.0, 0.1],
    }
    for parameter in spec["parameters"]:
        parameter.update({"scale": 1.0, "lower_bound": -5.0, "upper_bound": 5.0})
    specification_path.write_text(json.dumps(spec, indent=2) + "\n")
    output_dir = root / "evaluation"
    evaluate_reviewed_response_fit(
        campaign_path=campaign_path,
        specification_path=specification_path,
        output_dir=output_dir,
    )
    return output_dir / "response_fit_evaluation.json"


def test_fit_comparison_requires_like_for_like_distinct_hypotheses(
    tmp_path: Path,
) -> None:
    first = _fit_evaluation(tmp_path / "n1-n2", "periodicity-n1-n2")
    second = _fit_evaluation(tmp_path / "n1-n3", "periodicity-n1-n3")
    output = tmp_path / "comparison.json"
    comparison = compare_response_fit_evaluations(
        evaluation_paths=[first, second], output_path=output
    )
    assert comparison["status"] == (
        "human_hypothesis_and_regularization_selection_required"
    )
    assert comparison["simulation_ready"] is False
    assert comparison["gate_effect"] == "none"
    assert comparison["selection"] is None
    assert [item["hypothesis_id"] for item in comparison["hypotheses"]] == [
        "periodicity-n1-n2",
        "periodicity-n1-n3",
    ]
    assert comparison["training_dataset_ids"]
    assert comparison["validation_dataset_ids"]
    with pytest.raises(ValueError, match="distinct matching hypothesis"):
        compare_response_fit_evaluations(
            evaluation_paths=[first, first],
            output_path=tmp_path / "duplicate.json",
        )

    selection_path = tmp_path / "fit_selection.json"
    selection = build_response_fit_selection_template(
        comparison_path=output,
        output_path=selection_path,
    )
    with pytest.raises(ValueError, match="human review"):
        extract_reviewed_response_fit_candidate(
            selection_path=selection_path,
            output_path=tmp_path / "must-not-exist.json",
        )
    chosen = comparison["hypotheses"][0]["candidates"][0]
    selection.update(
        {
            "status": "reviewed",
            "reviewed_by": "Qualified Test Reviewer",
            "reviewed_at": "2026-09-04T22:30:00Z",
            "review_rationale": (
                "The synthetic candidate satisfies declared held-out limits and exercises "
                "the explicit non-releasing coefficient extraction boundary."
            ),
            "selection": {
                "hypothesis_id": "periodicity-n1-n2",
                "ridge_lambda": chosen["ridge_lambda"],
            },
            "acceptance_limits": {
                "validation_gradient_rmse_max": chosen["validation"]["gradient_rmse"]
                + 1.0e-6,
                "validation_hessian_rmse_max": chosen["validation"]["hessian_rmse"]
                + 1.0e-6,
                "validation_gradient_max_abs_max": chosen["validation"][
                    "gradient_max_abs"
                ]
                + 1.0e-6,
                "validation_hessian_max_abs_max": chosen["validation"][
                    "hessian_max_abs"
                ]
                + 1.0e-6,
                "active_bound_count_max": chosen["active_bound_count"],
            },
        }
    )
    selection_path.write_text(json.dumps(selection, indent=2) + "\n")
    selected_path = tmp_path / "selected_candidate.json"
    selected = extract_reviewed_response_fit_candidate(
        selection_path=selection_path,
        output_path=selected_path,
    )
    assert selected["status"] == (
        "human_selected_candidate_requires_charmm_mapping_and_validation"
    )
    assert selected["simulation_ready"] is False
    assert selected["gate_effect"] == "none"
    assert selected["hypothesis_id"] == "periodicity-n1-n2"
    assert selected["parameters"]
    assert selected["parameters"][0]["coefficient_units"] == "kcal/mol"
    assert selected["parameters"][0]["basis"] == "cos(1*phi)"
    assert all(item["passed"] for item in selected["selection_checks"].values())
    transform_path = tmp_path / "charmm_transform.json"
    transformed = build_charmm_bonded_transform_candidate(
        selected_candidate_path=selected_path,
        output_path=transform_path,
    )
    assert transformed["status"] == (
        "algebraically_transformed_requires_term_mapping_and_validation"
    )
    assert transformed["simulation_ready"] is False
    assert len(transformed["bonded_terms"]["dihedrals"]) == 3

    malformed = json.loads(selected_path.read_text())
    malformed["ridge_lambda"] = None
    selected_path.write_text(json.dumps(malformed, indent=2) + "\n")
    with pytest.raises(ValueError, match="provenance chain changed identity"):
        build_charmm_bonded_transform_candidate(
            selected_candidate_path=selected_path,
            output_path=tmp_path / "malformed-transform.json",
        )


def test_linear_basis_inverse_maps_harmonics_and_signed_cosines() -> None:
    theta0 = math.radians(105.0)
    improper_offset = math.radians(12.0)
    common_angle = {
        "group_id": "angle:test",
        "category": "angles",
        "occurrence_count": 2,
    }
    common_improper = {
        "group_id": "improper:C5",
        "category": "impropers",
        "occurrence_count": 1,
        "reference_degrees": 25.0,
        "ordered_atoms_candidate": ["C5", "C4", "C6", "C7"],
    }
    parameters = [
        {
            "group_id": "bond:test",
            "category": "bonds",
            "occurrence_count": 2,
            "name": "r2",
            "basis": "r^2",
            "coefficient_units": "kcal/mol/angstrom^2",
            "coefficient": 250.0,
        },
        {
            "group_id": "bond:test",
            "category": "bonds",
            "occurrence_count": 2,
            "name": "r",
            "basis": "r",
            "coefficient_units": "kcal/mol/angstrom",
            "coefficient": -750.0,
        },
        {
            **common_angle,
            "name": "theta2",
            "basis": "theta^2",
            "coefficient_units": "kcal/mol/rad^2",
            "coefficient": 30.0,
        },
        {
            **common_angle,
            "name": "theta",
            "basis": "theta",
            "coefficient_units": "kcal/mol/rad",
            "coefficient": -2.0 * 30.0 * theta0,
        },
        {
            **common_angle,
            "name": "r13_2",
            "basis": "r13^2",
            "coefficient_units": "kcal/mol/angstrom^2",
            "coefficient": 4.0,
        },
        {
            **common_angle,
            "name": "r13",
            "basis": "r13",
            "coefficient_units": "kcal/mol/angstrom",
            "coefficient": -16.0,
        },
        {
            "group_id": "dihedral:test",
            "category": "dihedrals",
            "occurrence_count": 1,
            "name": "cos1",
            "basis": "cos(1*phi)",
            "coefficient_units": "kcal/mol",
            "periodicity": 1,
            "coefficient": 2.5,
        },
        {
            "group_id": "dihedral:test",
            "category": "dihedrals",
            "occurrence_count": 1,
            "name": "cos2",
            "basis": "cos(2*phi)",
            "coefficient_units": "kcal/mol",
            "periodicity": 2,
            "coefficient": -1.25,
        },
        {
            **common_improper,
            "name": "delta2",
            "basis": "wrapped_delta^2",
            "coefficient_units": "kcal/mol/rad^2",
            "coefficient": 20.0,
        },
        {
            **common_improper,
            "name": "delta",
            "basis": "wrapped_delta",
            "coefficient_units": "kcal/mol/rad",
            "coefficient": -2.0 * 20.0 * improper_offset,
        },
    ]
    transformed = transform_linear_coefficients_to_charmm(parameters)
    bond = transformed["bonds"][0]
    assert bond["k_kcal_mol_a2"] == pytest.approx(250.0)
    assert bond["r0_angstrom"] == pytest.approx(1.5)
    angle = transformed["angles"][0]
    assert angle["k_kcal_mol_rad2"] == 30.0
    assert angle["theta0_degrees"] == pytest.approx(105.0)
    assert angle["urey_bradley"]["s0_angstrom"] == 2.0
    without_urey_bradley = [
        item for item in parameters if item.get("basis") not in {"r13^2", "r13"}
    ]
    angle_without_ub = transform_linear_coefficients_to_charmm(
        without_urey_bradley
    )["angles"][0]
    assert angle_without_ub["urey_bradley"] is None
    torsions = transformed["dihedrals"][0]["fourier_terms"]
    assert [(item["k_kcal_mol"], item["delta_degrees"]) for item in torsions] == [
        (2.5, 0.0),
        (1.25, 180.0),
    ]
    improper = transformed["impropers"][0]
    assert improper["k_kcal_mol_rad2"] == 20.0
    assert improper["psi0_degrees"] == pytest.approx(37.0)

    invalid = [dict(item) for item in parameters]
    invalid[2]["coefficient"] = -1.0
    with pytest.raises(ValueError, match="nonpositive curvature"):
        transform_linear_coefficients_to_charmm(invalid)


def test_linear_basis_inverse_keeps_fixed_qm_improper_reference() -> None:
    parameters = [
        {
            "group_id": "improper:C5",
            "category": "impropers",
            "occurrence_count": 1,
            "name": "delta2",
            "basis": "wrapped_delta^2",
            "coefficient_units": "kcal/mol/rad^2",
            "coefficient": 24.0,
            "reference_degrees": -32.47,
            "expected_signed_volume": "negative",
            "ordered_atoms_candidate": ["C5", "C4", "C6", "C7"],
        }
    ]

    transformed = transform_linear_coefficients_to_charmm(parameters)

    assert transformed["impropers"] == [
        {
            "group_id": "improper:C5",
            "occurrence_count": 1,
            "ordered_atoms_candidate": ["C5", "C4", "C6", "C7"],
            "k_kcal_mol_rad2": 24.0,
            "psi0_degrees": pytest.approx(-32.47),
            "source_coefficients": ["delta2"],
        }
    ]
