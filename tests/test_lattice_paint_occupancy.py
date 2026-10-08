"""Painted new features reject occupied addresses before preview or mutation."""
import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import state
from backend.core.models import Design
from backend.core.sweep import build_sweep, SweepRequest
from backend.core.lattice_frames import append_independent_bundle
from backend.core.lattice_occupancy import occupied_lattice_cells


@pytest.mark.parametrize('existing', ['sweep', 'extrude'])
@pytest.mark.parametrize('plane', ['XY', 'XZ', 'YZ'])
@pytest.mark.parametrize('tool', ['sweep', 'frame-extrusion'])
def test_occupied_cell_rejected_atomically(existing, plane, tool):
    design = Design()
    if existing == 'sweep':
        design = build_sweep(design, SweepRequest(cells=[(0,0)], plane=plane,
                             points_nm=[(0,0,0),(5,2,10),(0,0,20)]))
    else:
        design = append_independent_bundle(design, [[0,0]], 21, plane=plane)
    state.set_design(design)
    before = state.get_or_404().to_json()
    revision = state.revision()
    body = dict(cells=[[0,0],[0,1]], plane=plane, expected_design_id=design.id,
                expected_revision=revision)
    if tool == 'sweep':
        body['points_nm'] = [[0,0,0],[0,0,10]]
    else:
        body['length_bp'] = 21
    client = TestClient(app)
    for suffix in (('/preview' if tool=='sweep' else '/validate'), ''):
        response = client.post('/api/design/'+tool+suffix, json=body)
        assert response.status_code == 422, response.text
        assert 'occupied' in response.text
        assert state.revision() == revision and state.get_or_404().to_json() == before
    body['cells'] = [[0,1]]
    response = client.post('/api/design/'+tool, json=body)
    assert response.status_code == 201, response.text
    assert occupied_lattice_cells(state.get_or_404(), plane) == {(0,0),(0,1)}


def test_same_address_on_other_plane_is_available():
    design = append_independent_bundle(Design(), [[0,0]], 21, plane='XY')
    result = build_sweep(design, SweepRequest(cells=[(0,0)], plane='YZ', points_nm=[(0,0,0),(10,0,0)]))
    assert len(result.helices)==2


def test_legacy_non_xy_ids_supply_missing_grid_addresses():
    from backend.core.lattice import make_bundle_design
    design = make_bundle_design([(2,-3)],21,plane='XZ')
    design.helices[0].grid_pos = None
    assert occupied_lattice_cells(design,'XZ') == {(2,-3)}
    with pytest.raises(ValueError,match='occupied'):
        build_sweep(design,SweepRequest(cells=[(2,-3)],plane='XZ',points_nm=[(0,0,0),(0,10,0)]))
