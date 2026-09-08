"""Pre-QM OpenMM rank-screen tests for coupled conformer candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from openmm import CustomExternalForce, System, XmlSerializer

from backend.parameterization.photoproduct_conformer_screen import (
    compare_periodicity_rank_screens,
    screen_coupled_conformer_fit_rank,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _fixtures(tmp_path: Path) -> tuple[Path, Path, Path]:
    system = System()
    for _ in range(4):
        system.addParticle(12.0)
    force = CustomExternalForce("p*x*x+q*y*y")
    force.addGlobalParameter("p", 0.0)
    force.addGlobalParameter("q", 0.0)
    for index in range(4):
        force.addParticle(index, [])
    system.addForce(force)
    system_path = tmp_path / "system.xml"
    system_path.write_text(XmlSerializer.serialize(system))
    parameters = tmp_path / "parameters.json"
    _write_json(
        parameters,
        [
            {"name": "p", "default": 0.0, "group_id": "x", "category": "bonds"},
            {"name": "q", "default": 0.0, "group_id": "y", "category": "bonds"},
        ],
    )
    stable = tmp_path / "stable.json"
    _write_json(stable, [{"stable_atom_key": key} for key in ("A", "B", "C", "D")])
    basis = tmp_path / "basis.json"
    _write_json(
        basis,
        {
            "schema": "nadoc.photoproduct-openmm-linear-fit-basis.v1",
            "status": "candidate_basis_unfitted_not_releasable",
            "simulation_ready": False,
            "gate_effect": "none",
            "product_id": "fixture",
            "model_id": "model",
            "hypothesis_id": "hypothesis",
            "parameter_count": 2,
            "torsion_periodicities_to_test": [1, 2],
            "outputs": {
                "linear_fit_system": {
                    "path": str(system_path),
                    "sha256": _sha256(system_path),
                },
                "linear_parameter_map": {
                    "path": str(parameters),
                    "sha256": _sha256(parameters),
                },
            },
            "sources": {
                "stable_atom_map": {"path": str(stable), "sha256": _sha256(stable)}
            },
        },
    )
    baseline_arrays = tmp_path / "baseline.npz"
    np.savez_compressed(
        baseline_arrays,
        projected_design_gradient=np.asarray([[1.0, 0.0]]),
        projected_design_hessian_upper=np.asarray([[2.0, 0.0]]),
    )
    baseline = tmp_path / "baseline.json"
    _write_json(
        baseline,
        {
            "schema": "nadoc.photoproduct-openmm-linear-response.v1",
            "status": "candidate_response_unfitted_not_releasable",
            "simulation_ready": False,
            "gate_effect": "none",
            "product_id": "fixture",
            "model_id": "model",
            "hypothesis_id": "hypothesis",
            "sources": {
                "linear_parameter_map": {
                    "path": str(parameters),
                    "sha256": _sha256(parameters),
                },
                "stable_atom_map": {"path": str(stable), "sha256": _sha256(stable)},
            },
            "outputs": {
                "linear_response_arrays": {
                    "path": str(baseline_arrays),
                    "sha256": _sha256(baseline_arrays),
                }
            },
        },
    )
    geometries = []
    for identifier, delta in (("one", 0.0), ("two", 0.15)):
        xyz = tmp_path / f"{identifier}.xyz"
        xyz.write_text(
            "4\nfixture\n"
            f"C 0.0 0.0 0.0\nC {1.0 + delta} 0.0 0.0\n"
            "C 0.2 1.1 0.0\nC 0.1 0.2 1.2\n"
        )
        geometries.append(
            {"id": identifier, "geometry": {"path": str(xyz), "sha256": _sha256(xyz)}}
        )
    candidates = tmp_path / "candidates.json"
    _write_json(
        candidates,
        {
            "schema": "nadoc.photoproduct-coupled-conformer-candidates.v1",
            "status": "candidates_not_reviewed",
            "simulation_ready": False,
            "gate_effect": "none",
            "product_id": "fixture",
            "model_id": "model",
            "sources": {
                "stable_atom_map": {"path": str(stable), "sha256": _sha256(stable)}
            },
            "candidates": geometries,
        },
    )
    return basis, baseline, candidates


def test_rank_screen_is_gate_neutral_and_reports_gain(tmp_path: Path) -> None:
    basis, baseline, candidates = _fixtures(tmp_path)
    report = screen_coupled_conformer_fit_rank(
        fit_basis_manifest_path=basis,
        baseline_response_manifest_path=baseline,
        candidate_manifest_path=candidates,
        candidate_ids=["one", "two"],
        output_dir=tmp_path / "screen",
    )
    assert report["status"] == "diagnostic_only_candidates_not_reviewed"
    assert report["simulation_ready"] is False
    assert report["gate_effect"] == "none"
    assert report["baseline_rank"] == 1
    assert report["greedy_final_rank"] == 2
    assert report["greedy_rank_gain"] == 1
    with np.load(
        tmp_path / "screen" / "conformer_rank_screen_arrays.npz",
        allow_pickle=False,
    ) as arrays:
        assert arrays["projected_design_gradient"].shape == (2, 12, 2)

    second_basis = tmp_path / "basis_n1_n3.json"
    second_basis_payload = json.loads(basis.read_text())
    second_basis_payload["torsion_periodicities_to_test"] = [1, 2, 3]
    _write_json(second_basis, second_basis_payload)
    first_screen = tmp_path / "screen" / "conformer_rank_screen.json"
    second_screen = tmp_path / "second_screen.json"
    second_screen_payload = json.loads(first_screen.read_text())
    second_screen_payload["sources"]["fit_basis_manifest"] = {
        "path": str(second_basis),
        "sha256": _sha256(second_basis),
    }
    _write_json(second_screen, second_screen_payload)
    comparison = compare_periodicity_rank_screens(
        screen_manifest_paths=[first_screen, second_screen],
        output_path=tmp_path / "periodicity_comparison.json",
    )
    assert comparison["selection"] is None
    assert comparison["status"] == "human_model_selection_and_qm_validation_required"
    assert [item["periodicities"] for item in comparison["hypotheses"]] == [
        [1, 2],
        [1, 2, 3],
    ]


def test_rank_screen_rejects_unknown_candidate_before_output(tmp_path: Path) -> None:
    basis, baseline, candidates = _fixtures(tmp_path)
    with pytest.raises(ValueError, match="candidate IDs"):
        screen_coupled_conformer_fit_rank(
            fit_basis_manifest_path=basis,
            baseline_response_manifest_path=baseline,
            candidate_manifest_path=candidates,
            candidate_ids=["missing"],
            output_dir=tmp_path / "screen",
        )
