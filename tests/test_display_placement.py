"""Retired viewer positions cannot return through a debug flag or omitted header."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import state
from backend.api.main import app
from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from tests.conftest import make_minimal_design


@pytest.mark.parametrize("query", ["", "&apply_deformations=false", "&helix_ids=h0"])
def test_default_and_explicit_native_match_and_legacy_is_rejected(query, tmp_path, monkeypatch):
    monkeypatch.setenv("NADOC_PLACEMENT_REPORT_DIR", str(tmp_path / "incidents"))
    design = make_minimal_design()
    state.set_design(design)
    client = TestClient(app)
    responses = [
        client.get("/api/design/geometry?" + flag + query)
        for flag in ["measured_positioning=true", "measured_positioning=false", ""]
    ]
    assert responses[0].status_code == responses[2].status_code == 200
    assert responses[1].status_code == 500
    assert responses[1].json()["detail"]["code"] == "NATIVE_PLACEMENT_INTEGRITY"
    assert responses[0].json() == responses[2].json()
    if not query:
        assert responses[0].json()["nucleotides"] == _geometry_for_design(
            design, measured_positioning=True, junction_balance=True
        )


def test_atomistic_preserves_authored_cpd_and_rejects_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("NADOC_PLACEMENT_REPORT_DIR", str(tmp_path / "incidents"))
    design = Design.from_json(Path("tests/fixtures/cpd_2hb_1xt.nadoc").read_text())
    state.set_design(design)
    original = design.to_json()
    client = TestClient(app)
    on = client.get("/api/design/atomistic?measured_positioning=true")
    off = client.get("/api/design/atomistic?measured_positioning=false")
    default = client.get("/api/design/atomistic")
    assert on.status_code == default.status_code == 200
    assert off.status_code == 500
    assert off.json()["detail"]["code"] == "NATIVE_PLACEMENT_INTEGRITY"
    assert on.json() == default.json()
    assert state.get_or_404().to_json() == original
    from backend.core.native_full_placement import NativePlacementError
    with pytest.raises(NativePlacementError, match="removed"):
        build_atomistic_model(design, measured_positioning=False, fast_bridges=True)


def test_assembly_native_cache_cannot_serve_a_legacy_request(tmp_path, monkeypatch):
    monkeypatch.setenv("NADOC_PLACEMENT_REPORT_DIR", str(tmp_path / "incidents"))
    from backend.api import assembly_state
    from backend.core.assembly_geometry import clear_geo_cache
    from backend.core.models import Assembly, PartInstance, PartSourceInline

    design = make_minimal_design()
    inst = PartInstance(source=PartSourceInline(design=design))
    assembly_state.set_assembly(Assembly(instances=[inst]))
    clear_geo_cache()
    client = TestClient(app)
    try:
        for path in [
            f"/api/assembly/instances/{inst.id}/geometry",
            "/api/assembly/geometry",
        ]:
            native = client.get(path + "?measured_positioning=true")
            baseline = client.get(path + "?measured_positioning=false")
            default = client.get(path)
            assert native.status_code == default.status_code == 200
            assert baseline.status_code == 500
            assert baseline.json()["detail"]["code"] == "NATIVE_PLACEMENT_INTEGRITY"
            assert native.json() == default.json()
    finally:
        clear_geo_cache()


def test_legacy_header_is_rejected_before_any_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("NADOC_PLACEMENT_REPORT_DIR", str(tmp_path / "incidents"))
    design = make_minimal_design()
    state.load_design(design)
    before = state.get_or_404().to_json()
    response = TestClient(app).put("/api/design/nucleotide-transform", headers={
        "X-NADOC-Measured-Positioning": "false"}, json={
        "kind": "base", "helix_id": "h0", "bp_index": 4, "direction": "FORWARD",
        "copy_k": 0, "pivot": [0, 0, 0], "translation": [1, 0, 0], "rotation": [0, 0, 0, 1]})
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "NATIVE_PLACEMENT_INTEGRITY"
    assert state.get_or_404().to_json() == before


def test_atomistic_cache_rejects_deleted_option_before_lookup():
    from backend.core.atomistic_cache import build_atomistic_model_cached
    from backend.core.native_full_placement import NativePlacementError
    with pytest.raises(NativePlacementError, match="removed"):
        build_atomistic_model_cached(make_minimal_design(), measured_positioning=False)
