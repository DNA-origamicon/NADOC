"""Identity placement must not double the cost of loop geometry responses."""
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import state
from tests.test_strand_loops import process, params


def test_identity_cluster_does_not_recompute_straight_geometry(monkeypatch):
    from backend.api import crud
    p = process()
    p.append('strand-loop-set', params(p.design.strands[0], 6), 'Add loop')
    assert p.design.cluster_transforms
    previous = state.get_design()
    try:
        state.set_design(p.design)
        def redundant(*args, **kwargs):
            raise AssertionError('Identity placement recomputed straight geometry')
        monkeypatch.setattr(crud, '_positions_for_design', redundant)
        response = TestClient(app).get('/api/design/geometry')
        assert response.status_code == 200
        body = response.json()
        assert len(body['nucleotides']) == 48
        assert 'straight_positions_by_helix' not in body
    finally:
        state.set_design(previous)
