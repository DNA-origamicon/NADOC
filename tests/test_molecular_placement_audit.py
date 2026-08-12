"""Read-only evidence bundle for the Molecular Placement Audit view."""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.atomistic import build_atomistic_model
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


def test_longer_runs_report_that_the_geometric_baseline_is_already_native():
    bundle = build_molecular_placement_audit(reciprocal_design("TT", bp=12))
    assert bundle["displacement"]["n_displaced"] == 0
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
