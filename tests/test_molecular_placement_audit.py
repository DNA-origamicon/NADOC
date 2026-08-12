"""Read-only evidence bundle for the Molecular Placement Audit view."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.atomistic import build_atomistic_model
from backend.core.models import NucleotideTransform
from backend.core.molecular_placement_audit import (
    _defect_serials,
    build_molecular_placement_audit,
)
from tests.reciprocal_design import reciprocal_design


def _xyz(model):
    return np.asarray([[a.x, a.y, a.z] for a in model.atoms])


def test_audit_candidate_is_isolated_and_moves_only_insert_residues():
    design = reciprocal_design("T", bp=12)
    before_json = design.model_dump_json()
    production_before = build_atomistic_model(design, fast_bridges=True)

    bundle = build_molecular_placement_audit(design)

    production_after = build_atomistic_model(design, fast_bridges=True)
    assert design.model_dump_json() == before_json
    assert np.array_equal(_xyz(production_before), _xyz(production_after))
    assert production_before.bonds == production_after.bonds
    assert bundle["read_only"] is True
    assert bundle["provider"]["not_authorized_for_production"] is True
    assert bundle["displacement"]["n_displaced"] > 0

    displaced = set(
        bundle["displacement"]["vectors"][i]["serial"]
        for i in range(bundle["displacement"]["n_displaced"])
    )
    current_atoms = bundle["current"]["atoms"]
    assert all(current_atoms[i]["extra_base_k"] is not None for i in displaced)


def test_two_base_runs_show_promoted_production_v7_in_both_panels():
    bundle = build_molecular_placement_audit(reciprocal_design("TT", bp=12))
    assert bundle["provider"]["id"] == "reciprocal-phosphate-clearance-production-v7"
    assert bundle["provider"]["panel_labels"] == {
        "current": "Production v7",
        "candidate": "Production v7",
    }
    assert bundle["provider"]["not_authorized_for_production"] is False
    assert bundle["provider"]["promoted_to_production"] is True
    assert bundle["displacement"]["n_displaced"] == 0
    assert bundle["current_design"] == bundle["candidate_design"]
    planes = bundle["midpoint_constraint_planes"]
    assert len(planes) == 1
    for plane in planes:
        assert np.linalg.norm(plane["normal"]) == pytest.approx(1.0)
        assert plane["radius_nm"] >= 0.65
        assert len(plane["crossover_ids"]) == 2
        assert plane["bp_indices"][1] - plane["bp_indices"][0] == pytest.approx(1.0)


def test_runs_longer_than_two_remain_at_the_geometric_baseline():
    bundle = build_molecular_placement_audit(reciprocal_design("TTT", bp=12))
    assert bundle["displacement"]["n_displaced"] == 0
    assert bundle["displacement"]["max_nm"] == 0.0


def test_authored_two_base_pair_still_uses_production_v7():
    design = reciprocal_design("TT", bp=12)
    target = design.crossovers[0].id
    design = design.copy_with(nucleotide_transforms=[
        NucleotideTransform(
            kind="extra_base", crossover_id=target, extra_base_k=k,
            pivot=[0.0, 0.0, 0.0],
        )
        for k in range(2)
    ])
    bundle = build_molecular_placement_audit(design)
    assert bundle["provider"]["id"] == "reciprocal-phosphate-clearance-production-v7"
    assert bundle["provider"]["promoted_to_production"] is True
    assert bundle["provider"]["not_authorized_for_production"] is False
    assert target in bundle["provider"]["target_crossover_ids"]
    assert len(bundle["provider"]["target_crossover_ids"]) == 2
    assert bundle["proposal_validation"] is not None
    assert bundle["displacement"]["max_nm"] == 0.0


def test_defect_focus_uses_the_exact_clashing_atom_pairs():
    diagnostics = {
        "piercing": {"pierced": []},
        "clashes": [
            {"serials": [8, 3], "distance_nm": 0.041},
            {"serials": [5, 8], "distance_nm": 0.052},
        ],
    }
    assert _defect_serials(diagnostics) == [3, 5, 8]


def test_defect_focus_is_exact_union_of_piercing_and_clash_atoms():
    bundle = build_molecular_placement_audit(reciprocal_design("T", bp=8))
    diagnostics = bundle["candidate"]["diagnostics"]
    piercing_hits = diagnostics["piercing"]["pierced"]
    expected_piercing = {
        serial
        for hit in piercing_hits
        for serial in hit["bond_serials"] + hit["ring_serials"]
    }
    expected_clashes = {
        serial for hit in diagnostics["clashes"] for serial in hit["serials"]
    }
    assert piercing_hits
    assert set(bundle["defect_atom_serials"]["candidate"]) == (
        expected_piercing | expected_clashes
    )


def test_route_returns_full_and_ballstick_feeds_without_mutating_state():
    design = reciprocal_design("T", bp=12)
    design_state.set_design(design)
    before = design_state.get_or_404().model_dump_json()

    response = TestClient(app).get("/api/design/molecular-placement-audit")

    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "nadoc.molecular-placement-audit.v1"
    assert body["nucleotides"]
    assert body["helix_axes"]
    assert body["current"]["atoms"] and body["current"]["bonds"]
    assert body["candidate"]["atoms"] and body["candidate"]["bonds"]
    assert body["candidate_design"]["nucleotide_transforms"]
    assert design_state.get_or_404().model_dump_json() == before
