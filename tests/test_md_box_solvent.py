from backend.core.models import Design
from backend.api.routes_md import CreateJobRequest
from backend.core import md_box_preview


def test_explicit_empty_box_never_requests_dna_geometry(monkeypatch):
    def forbidden(*args):
        raise AssertionError('Explicit electrolyte box must not fit DNA geometry')
    monkeypatch.setattr(md_box_preview,'_calculated_box',forbidden)
    result=md_box_preview.preview_box(Design(),CreateJobRequest(box_size_nm=[10,15,20],padding_nm=2))
    assert result['selected_nm']==[10,15,20]
    assert result['calculated_nm']==[10,15,20]
    assert result['padding_nm']==2


def test_box_solvent_metadata_roundtrip():
    from fastapi.testclient import TestClient
    from fastapi import HTTPException
    from backend.api.main import app
    from backend.api import state
    try:
        previous = state.get_or_404()
    except HTTPException:
        previous = None
    try:
        state.set_design(Design())
        values = {"sizing": "explicit", "x": "10", "y": "15", "z": "20", "salt": "custom", "na": "175", "mg": "0"}
        response = TestClient(app).put("/api/design/metadata", json={"namd_box_solvent": values})
        assert response.status_code == 200
        restored = Design.model_validate_json(Design.model_validate(response.json()["design"]).model_dump_json())
        assert restored.metadata.namd_box_solvent == values
        assert not restored.helices
    finally:
        state.set_design(previous)
