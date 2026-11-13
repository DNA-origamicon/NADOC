"""Regression coverage for metadata-only overhang label edits."""

from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api import crud
from tests.conftest import valid_overhang_sites


client = TestClient(app)


def _design_with_overhang():
    crud.create_bundle(crud.BundleRequest(
        cells=[[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]], length_bp=42))
    site = valid_overhang_sites(design_state.get_or_404())[0]
    crud.overhang_extrude(crud.OverhangExtrudeRequest(**site, length_bp=8))
    return design_state.get_or_404()



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
