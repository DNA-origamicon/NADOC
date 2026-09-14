from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.parameterization.photoproduct_bonded_refit import (
    promote_bonded_fit_terms,
)


RING = ["1:C5", "1:C6", "2:C6", "2:C5"]


def _record(category: str, atoms: list[str], types: list[str]) -> dict:
    record = {
        "category": category,
        "atoms": atoms,
        "types": types,
        "coverage": "exact",
        "matches": [{"values": [1.0, 2.0]}],
        "observed_coordinate": 1.5,
        "coordinate_unit": "angstrom" if category == "bonds" else "degree",
        "status": "transfer_candidate_requires_review",
    }
    if category == "dihedrals":
        record.update(
            central_bond=atoms[1:3],
            central_bond_order=1.0,
            central_bond_in_cycle=True,
            target_class="coupled_ring_response_no_independent_scan",
        )
    return record


def _inputs(tmp_path: Path, *, omit_last: bool = False) -> tuple[Path, Path]:
    paths = {
        "bonds": [[RING[i], RING[(i + 1) % 4]] for i in range(4)],
        "angles": [
            [RING[i], RING[(i + 1) % 4], RING[(i + 2) % 4]]
            for i in range(4)
        ],
        "dihedrals": [RING[i:] + RING[:i] for i in range(4)],
    }
    records = [
        _record(category, atoms, ["CR"] * len(atoms))
        for category, atom_paths in paths.items()
        for atoms in atom_paths
    ]
    if omit_last:
        records.pop()
    plan = {
        "schema": "nadoc.photoproduct-bonded-fit-plan.v1",
        "status": "candidate_plan_unassigned_not_releasable",
        "gate_effect": "none",
        "product_id": "tt-cpd-cis-syn",
        "model_id": "n-methyl",
        "hypothesis_id": "test",
        "transfer_candidates": records,
        "uncovered_parameter_groups": [],
        "stereochemical_impropers": [],
        "sources": {},
        "release_blockers": [],
    }
    policy = {
        "schema": "nadoc.photoproduct-bonded-refit-policy.v1",
        "version": "test",
        "status": "workflow_policy",
        "product_id": "tt-cpd-cis-syn",
        "variant_family": "test-ring-refit",
        "selection": {
            "stable_ring_atoms": ["1:C5", "1:C6", "2:C5", "2:C6"],
            "categories": ["bonds", "angles", "dihedrals"],
            "rule": "unit test",
            "expected_occurrence_counts": {
                "bonds": 4,
                "angles": 4,
                "dihedrals": 4,
            },
            "allow_partial_ring_promotion": False,
        },
    }
    plan_path = tmp_path / "fit_plan.json"
    policy_path = tmp_path / "policy.json"
    plan_path.write_text(json.dumps(plan))
    policy_path.write_text(json.dumps(policy))
    return plan_path, policy_path


def test_complete_ring_block_is_promoted_and_hash_linked(tmp_path: Path):
    plan_path, policy_path = _inputs(tmp_path)
    output = tmp_path / "promoted.json"

    result = promote_bonded_fit_terms(
        fit_plan_path=plan_path,
        policy_path=policy_path,
        output_path=output,
    )

    assert result["transfer_candidates"] == []
    assert len(result["promoted_transfer_candidates"]) == 12
    assert result["bonded_refit"]["occurrence_counts"] == {
        "bonds": 4,
        "angles": 4,
        "dihedrals": 4,
    }
    assert len(result["uncovered_parameter_groups"]) == 3
    assert all(
        group["parameter_origin"] == "promoted_pinned_transfer"
        for group in result["uncovered_parameter_groups"]
    )
    assert result["sources"]["parent_fit_plan"]["sha256"]
    assert result["sources"]["bonded_refit_policy"]["sha256"]


def test_partial_ring_block_fails_closed(tmp_path: Path):
    plan_path, policy_path = _inputs(tmp_path, omit_last=True)

    with pytest.raises(ValueError, match="promotion count differs"):
        promote_bonded_fit_terms(
            fit_plan_path=plan_path,
            policy_path=policy_path,
            output_path=tmp_path / "promoted.json",
        )


def test_v2_policy_allows_an_independent_noncanonical_ordered_product(tmp_path: Path):
    plan_path, _policy_path = _inputs(tmp_path)
    plan = json.loads(plan_path.read_text())
    plan["product_id"] = "tt-cpd-trans-anti-ii"
    plan_path.write_text(json.dumps(plan))
    policy_path = (
        Path(__file__).parents[1]
        / "backend/data/forcefield/photoproduct_bonded_refit_policy_v2.json"
    )

    result = promote_bonded_fit_terms(
        fit_plan_path=plan_path,
        policy_path=policy_path,
        output_path=tmp_path / "promoted.json",
    )

    assert result["product_id"] == "tt-cpd-trans-anti-ii"
    assert result["bonded_refit"]["group_count"] == 3
