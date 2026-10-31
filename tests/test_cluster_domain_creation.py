"""Domain cluster creation validates membership without crashing or mutating state."""
import pytest
from fastapi.testclient import TestClient
from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import Design, Helix, Strand, Domain, Vec3

@pytest.fixture
def client():
    design_state.set_design(Design(helices=[Helix(id='h', length_bp=20,
        axis_start=Vec3(x=0, y=0, z=0), axis_end=Vec3(x=0, y=0, z=6.8))],
        strands=[Strand(id='s', domains=[Domain(direction='FORWARD', helix_id='h', start_bp=0, end_bp=9),
                                        Domain(direction='FORWARD', helix_id='h', start_bp=10, end_bp=19)])]))
    yield TestClient(app)
    design_state.set_design(_demo_design())


def test_create_exact_domain_cluster(client):
    response = client.post('/api/design/cluster', json={'name': 'Selected domains',
        'helix_ids': ['h'], 'domain_ids': [{'strand_id': 's', 'domain_index': 1}]})
    assert response.status_code == 200, response.text
    cluster = response.json()['design']['cluster_transforms'][-1]
    assert cluster['domain_ids'] == [{'strand_id': 's', 'domain_index': 1}]


@pytest.mark.parametrize('index', [-1, 2, 99])
def test_invalid_domain_returns_client_error_without_mutation(client, index):
    before = design_state.get_or_404().model_dump()
    depth = design_state.undo_depth()
    response = client.post('/api/design/cluster', json={'helix_ids': ['h'],
        'domain_ids': [{'strand_id': 's', 'domain_index': 0}, {'strand_id': 's', 'domain_index': index}]})
    assert response.status_code == 422
    assert 'Missing domain' in response.json()['detail']
    assert design_state.get_or_404().model_dump() == before
    assert design_state.undo_depth() == depth
