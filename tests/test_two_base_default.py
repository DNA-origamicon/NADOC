"""Production contract for the owner-authorized v7 reciprocal 2xT default."""

from pathlib import Path

import numpy as np
import pytest

from backend.core.atomistic import build_atomistic_model
from backend.core.models import Design
from backend.core.molecular_placement_audit import (
    _midpoint_constraint_planes,
    _model_diagnostics,
    build_molecular_placement_audit,
)


@pytest.mark.parametrize("fixture", ["6hb_2xT", "2x3SQx32_2xT"])
@pytest.mark.parametrize("fast_bridges", [True, False])
def test_production_two_base_default_has_no_insert_defects(fixture, fast_bridges):
    design = Design.from_json(
        (Path(__file__).parents[1] / "workspace" / f"{fixture}.nadoc").read_text()
    )
    legacy = build_atomistic_model(
        design,
        fast_bridges=fast_bridges,
        _two_base_default=False,
    )
    records: list[dict] = []
    model = build_atomistic_model(
        design,
        fast_bridges=fast_bridges,
        _extra_base_placement_sink=records,
    )
    diagnostics = _model_diagnostics(design, model)
    target_ids = {
        atom.crossover_id for atom in model.atoms if atom.crossover_id is not None
    }

    # v7 promotes the final reciprocal-phosphate clearance to every native
    # structure/export/simulation build, so whole-model nonbonded clashes are zero.
    assert diagnostics["n_clashes"] == 0

    assert not [
        hit for hit in diagnostics["clashes"]
        if any(model.atoms[i].crossover_id in target_ids for i in hit["serials"])
    ]
    assert not [
        hit for hit in diagnostics["piercing"]["pierced"]
        if set(hit["crossover_ids"]) & target_ids
    ]
    assert not [
        hit for hit in diagnostics["bonds"]["overstretched"]
        if any(model.atoms[i].crossover_id in target_ids for i in hit["serials"])
    ]

    positions = np.asarray([[a.x, a.y, a.z] for a in model.atoms], dtype=float)
    legacy_positions = np.asarray(
        [[a.x, a.y, a.z] for a in legacy.atoms], dtype=float
    )
    for plane in _midpoint_constraint_planes(records):
        origin = np.asarray(plane["origin"], dtype=float)
        normal = np.asarray(plane["normal"], dtype=float)
        for crossover_id in plane["crossover_ids"]:
            serials = [
                atom.serial for atom in model.atoms
                if atom.crossover_id == crossover_id
            ]
            # "Their side" is defined by the retired placement, not by whichever
            # side the promoted atoms happen to occupy after the transform.
            legacy_signed = (legacy_positions[serials] - origin) @ normal
            signed = (positions[serials] - origin) @ normal
            expected = 1.0 if float(np.mean(legacy_signed)) >= 0.0 else -1.0
            assert np.all(expected * signed >= 0.0)


@pytest.mark.parametrize("fixture", ["6hb_2xT", "2x3SQx32_2xT"])
@pytest.mark.slow
def test_auditor_shows_promoted_production_v7_without_a_pending_proposal(fixture):
    design = Design.from_json(
        (Path(__file__).parents[1] / "workspace" / f"{fixture}.nadoc").read_text()
    )
    bundle = build_molecular_placement_audit(design)

    assert bundle["provider"]["panel_labels"] == {
        "current": "Production v7",
        "candidate": "Production v7",
    }
    assert bundle["provider"]["promoted_to_production"] is True
    assert bundle["provider"]["not_authorized_for_production"] is False
    assert bundle["current"]["diagnostics"]["n_clashes"] == 0
    assert bundle["candidate"]["diagnostics"]["n_clashes"] == 0
    assert bundle["candidate"]["diagnostics"]["piercing"]["n_pierced"] == 0
    assert bundle["midpoint_plane_violations"]["candidate"] == []
    assert bundle["proposal_validation"]["target_overstretched_bonds"]["candidate"] == 0
    assert bundle["proposal_validation"]["clearance_candidate"] is None
    assert bundle["displacement"]["n_displaced"] == 0
