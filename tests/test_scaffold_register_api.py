import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.routes_scaffold_register import fingerprint
from tests.test_scaffold_register import circle_design


@pytest.fixture
def client():
    doc = 'scaffold-register-test'
    token = set_current_doc(doc)
    state.load_design(circle_design())
    try:
        yield TestClient(app, headers={'X-NADOC-Doc': doc})
    finally:
        state.close_session()
        reset_current_doc(token)


def test_sweep_apply_undo_and_stale_results(client):
    before = state.get_or_404().model_dump()
    response = client.post('/api/design/scaffold-register/sweep', json={})
    assert response.status_code == 200, response.text
    r = response.json()
    assert state.get_or_404().model_dump() == before
    assert r['elapsed_seconds'] > 0
    body = {**r['conditions'], 'cut_index': 5, 'expected_revision': r['revision'], 'design_id': r['design_id'], 'source_fingerprint': r['source_fingerprint']}
    # Harmless background metadata must not invalidate the scored topology.
    state.set_design(state.get_or_404().model_copy(update={'name': 'renamed in background'}))
    applied = client.post('/api/design/scaffold-register/apply', json=body)
    assert applied.status_code == 200, applied.text
    after = state.get_or_404()
    assert after.strands[0].domains[0].start_bp == 14
    assert after.strands[0].sequence == before['strands'][0]['sequence']
    assert after.strands[1].sequence != before['strands'][1]['sequence']
    assert after.feature_log[-1].label == 'Optimize scaffold sequence start (circular)'
    snapshot = after.model_dump()
    assert client.post('/api/design/scaffold-register/apply', json=body).status_code == 409
    assert state.get_or_404().model_dump() == snapshot
    assert client.post('/api/design/undo').status_code == 200
    restored = state.get_or_404()
    assert [s.model_dump() for s in restored.strands] == before['strands']


def test_invalid_apply_and_conditions_do_not_mutate(client):
    before = state.get_or_404().model_dump()
    for settings in ({'staple_nM': 1}, {'magnesium_mM': 0, 'tris_mM': 0}):
        assert client.post('/api/design/scaffold-register/sweep', json=settings).status_code == 422
    body = {'cut_index': 55, 'expected_revision': state.revision(), 'design_id': before['id'], 'source_fingerprint': fingerprint(state.get_or_404())}
    assert client.post('/api/design/scaffold-register/apply', json=body).status_code == 422
    body.update(cut_index=5, design_id='another-design')
    assert client.post('/api/design/scaffold-register/apply', json=body).status_code == 409
    assert state.get_or_404().model_dump() == before
