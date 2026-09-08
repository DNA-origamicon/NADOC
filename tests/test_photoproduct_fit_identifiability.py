"""Rank/null-space auditing for photoproduct bonded-fit responses."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from backend.parameterization.photoproduct_fit_identifiability import (
    audit_openmm_fit_identifiability,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    parameter_map = tmp_path / "parameters.json"
    parameter_map.write_text(
        json.dumps(
            [
                {"name": "a", "group_id": "angle:a", "category": "angles"},
                {"name": "b", "group_id": "angle:a", "category": "angles"},
                {"name": "c", "group_id": "dihedral:c", "category": "dihedrals"},
            ]
        )
        + "\n"
    )
    arrays = tmp_path / "response.npz"
    # b is exactly twice a, while c is independent: rank 2, nullity 1.
    matrix = np.asarray([[1.0, 2.0, 0.0], [0.0, 0.0, 1.0], [1.0, 2.0, 1.0]])
    np.savez_compressed(
        arrays,
        projected_design_gradient=matrix,
        projected_design_hessian_upper=matrix,
    )
    fit_plan = tmp_path / "fit-plan.json"
    fit_plan.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-bonded-fit-plan.v1",
                "status": "candidate_plan_unassigned_not_releasable",
                "product_id": "tt-cpd-cis-syn",
                "model_id": "model",
                "hypothesis_id": "hypothesis",
                "uncovered_parameter_groups": [
                    {
                        "id": "angle:a",
                        "category": "angles",
                        "occurrences": [{"atoms": ["1:A", "1:B", "1:C"]}],
                        "additional_target_requirement": "coupled_cartesian_hessian_and_mm_minimum",
                    },
                    {
                        "id": "dihedral:c",
                        "category": "dihedrals",
                        "occurrences": [
                            {
                                "atoms": ["1:A", "1:B", "1:C", "1:D"],
                                "target_class": "coupled_ring_response_no_independent_scan",
                            }
                        ],
                        "additional_target_requirement": "coupled_ring_hessians_and_multiple_conformers",
                    },
                ],
                "stereochemical_impropers": [],
            }
        )
        + "\n"
    )
    fit_basis = tmp_path / "fit-basis.json"
    fit_basis.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-openmm-linear-fit-basis.v1",
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
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-openmm-linear-response.v1",
                "status": "candidate_response_unfitted_not_releasable",
                "simulation_ready": False,
                "gate_effect": "none",
                "product_id": "tt-cpd-cis-syn",
                "model_id": "model",
                "hypothesis_id": "hypothesis",
                "parameter_count": 3,
                "outputs": {
                    "linear_response_arrays": {
                        "path": str(arrays),
                        "sha256": _sha256(arrays),
                    }
                },
                "sources": {
                    "fit_basis_manifest": {
                        "path": str(fit_basis),
                        "sha256": _sha256(fit_basis),
                    },
                    "linear_parameter_map": {
                        "path": str(parameter_map),
                        "sha256": _sha256(parameter_map),
                    }
                },
            }
        )
        + "\n"
    )
    return manifest, fit_plan


def test_audit_reports_nullity_and_evidence_without_advancing_gate(tmp_path: Path) -> None:
    manifest, fit_plan = _fixture(tmp_path)
    report = audit_openmm_fit_identifiability(
        response_manifest_path=manifest,
        fit_plan_path=fit_plan,
        output_path=tmp_path / "audit.json",
    )
    assert report["status"] == "underdetermined_additional_qm_evidence_required"
    assert report["gate_effect"] == "none"
    assert report["simulation_ready"] is False
    assert report["projected_hessian_block"]["rank"] == 2
    assert report["projected_hessian_block"]["nullity"] == 1
    assert report["joint_normalized_diagnostic_block"]["nullity"] == 1
    assert report["unresolved_categories"] == ["angles"]
    pairs = report["projected_hessian_block"]["near_collinear_parameter_pairs"]
    assert pairs[0]["parameter_1"] == "a"
    assert pairs[0]["parameter_2"] == "b"


def test_audit_rejects_hash_mismatch_and_overwrite(tmp_path: Path) -> None:
    manifest, fit_plan = _fixture(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["outputs"]["linear_response_arrays"]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload) + "\n")
    with pytest.raises(ValueError, match="hash-mismatched"):
        audit_openmm_fit_identifiability(
            response_manifest_path=manifest,
            fit_plan_path=fit_plan,
            output_path=tmp_path / "audit.json",
        )
    output = tmp_path / "existing.json"
    output.write_text("keep")
    with pytest.raises(FileExistsError, match="overwrite"):
        audit_openmm_fit_identifiability(
            response_manifest_path=manifest,
            fit_plan_path=fit_plan,
            output_path=output,
        )


def test_wide_gradient_block_retains_omitted_exact_null_directions(
    tmp_path: Path,
) -> None:
    manifest, fit_plan = _fixture(tmp_path)
    payload = json.loads(manifest.read_text())
    arrays_path = Path(payload["outputs"]["linear_response_arrays"]["path"])
    wide = np.asarray([[1.0, 0.0, 0.0]])
    np.savez_compressed(
        arrays_path,
        projected_design_gradient=wide,
        projected_design_hessian_upper=np.eye(3),
    )
    payload["outputs"]["linear_response_arrays"]["sha256"] = _sha256(arrays_path)
    manifest.write_text(json.dumps(payload) + "\n")
    report = audit_openmm_fit_identifiability(
        response_manifest_path=manifest,
        fit_plan_path=fit_plan,
        output_path=tmp_path / "wide-audit.json",
    )
    gradient = report["projected_gradient_block"]
    assert gradient["rank"] == 1
    assert gradient["nullity"] == 2
    assert len(gradient["null_directions"]) == 2
    assert gradient["null_directions"][-1]["singular_value"] == 0.0


def test_ring_dihedral_requires_coupled_evidence_not_a_torsion_scan(
    tmp_path: Path,
) -> None:
    manifest, fit_plan = _fixture(tmp_path)
    payload = json.loads(manifest.read_text())
    arrays_path = Path(payload["outputs"]["linear_response_arrays"]["path"])
    # Leave the ring-dihedral column unresolved while both angle columns are independent.
    matrix = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    np.savez_compressed(
        arrays_path,
        projected_design_gradient=matrix,
        projected_design_hessian_upper=matrix,
    )
    payload["outputs"]["linear_response_arrays"]["sha256"] = _sha256(arrays_path)
    manifest.write_text(json.dumps(payload) + "\n")
    report = audit_openmm_fit_identifiability(
        response_manifest_path=manifest,
        fit_plan_path=fit_plan,
        output_path=tmp_path / "ring-audit.json",
    )
    requirement = report["unresolved_group_requirements"][0]
    assert requirement["group_id"] == "dihedral:c"
    assert "do not independently scan a cyclic central bond" in requirement[
        "additional_evidence_required"
    ]
    assert not any(
        "relaxed QM torsion surfaces" in item
        for item in report["additional_evidence_required"]
    )
