"""Regression coverage for metadata-only overhang label edits."""

from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import OverhangSpec


client = TestClient(app)


def _design_with_overhang():
    design = _demo_design()
    strand = design.strands[0]
    domain = strand.domains[0].model_copy(update={"overhang_id": "oh_test"})
    strand = strand.model_copy(update={"domains": [domain, *strand.domains[1:]]})
    spec = OverhangSpec(
        id="oh_test", helix_id=domain.helix_id, strand_id=strand.id, sequence="ACGT"
    )
    return design.model_copy(update={"strands": [strand, *design.strands[1:]], "overhangs": [spec]})


def test_overhang_label_patch_flags_geometry_unchanged():
    design = _design_with_overhang()
    design_state.set_design(design)

    response = client.patch(
        f"/api/design/overhang/{design.overhangs[0].id}",
        json={"label": "Handle"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["geometry_unchanged"] is True
    assert "nucleotides" not in body
    assert "nucleotides_compact" not in body


def test_overhang_sequence_patch_does_not_claim_geometry_unchanged():
    design = _design_with_overhang()
    design_state.set_design(design)

    response = client.patch(
        f"/api/design/overhang/{design.overhangs[0].id}",
        json={"sequence": "ACGT"},
    )

    assert response.status_code == 200, response.text
    assert response.json().get("geometry_unchanged") is not True
