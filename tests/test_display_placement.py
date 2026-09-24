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
def test_both_comparison_slots_and_default_serve_native_geometry(query):
    design = make_minimal_design()
    state.set_design(design)
    client = TestClient(app)
    responses = [
        client.get("/api/design/geometry?" + flag + query)
        for flag in ["measured_positioning=true", "measured_positioning=false", ""]
    ]
    assert all(r.status_code == 200 for r in responses)
    assert responses[0].json() == responses[1].json() == responses[2].json()
    if not query:
        assert responses[0].json()["nucleotides"] == _geometry_for_design(
            design, measured_positioning=True, junction_balance=True
        )


def test_both_atomistic_slots_preserve_the_authored_cpd_and_native_neighbors():
    design = Design.from_json(Path("tests/fixtures/cpd_2hb_1xt.nadoc").read_text())
    state.set_design(design)
    original = design.to_json()
    client = TestClient(app)
    on = client.get("/api/design/atomistic?measured_positioning=true")
    off = client.get("/api/design/atomistic?measured_positioning=false")
    default = client.get("/api/design/atomistic")
    assert on.status_code == off.status_code == default.status_code == 200
    assert on.json() == off.json() == default.json()
    assert state.get_or_404().to_json() == original
    # Core callers using the retired flag also get the accepted geometry.
    a = build_atomistic_model(design, fast_bridges=True)
    b = build_atomistic_model(design, measured_positioning=False, fast_bridges=True)
    assert [(p.x, p.y, p.z) for p in a.atoms] == [(p.x, p.y, p.z) for p in b.atoms]
    assert a.bonds == b.bonds


def test_assembly_comparison_slots_share_the_native_cached_projection():
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
            assert (
                native.status_code == baseline.status_code == default.status_code == 200
            )
            assert native.json() == baseline.json() == default.json()
    finally:
        clear_geo_cache()
