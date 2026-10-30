"""Deferred authoring keeps the existing partial geometry and topology contract."""
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import state
from backend.core.lattice import make_bundle_design


def test_nick_and_ligate_deferred_geometry_matches_full_source():
    design = make_bundle_design([(0, 0), (0, 1), (1, 0), (1, 1)], 42)
    state.set_design(design)
    client = TestClient(app)
    hid = design.helices[0].id
    nick = client.post('/api/design/nick', json={
        'helix_id': hid, 'bp_index': 20, 'direction': 'FORWARD',
    }, headers={'X-NADOC-Skip-Geometry': '1'})
    assert nick.status_code == 201, nick.text
    result = nick.json()
    assert result['deferred_geometry_helix_ids'] == [hid]
    assert 'nucleotides' not in result
    pieces = [s for s in result['design']['strands'] if any(
        d['helix_id'] == hid and d['direction'] == 'FORWARD' for d in s['domains'])]
    a = next(s for s in pieces if s['domains'][-1]['end_bp'] == 20)
    b = next(s for s in pieces if s['domains'][0]['start_bp'] == 21)
    def check(response):
        assert response['deferred_geometry_helix_ids'] == [hid]
        partial = client.get('/api/design/geometry', params={'helix_ids': hid}).json()
        full = client.get('/api/design/geometry').json()
        assert partial['partial_geometry'] is True
        assert partial['changed_helix_ids'] == [hid]
        assert partial['nucleotides'] == [n for n in full['nucleotides'] if n['helix_id'] == hid]
        assert len(partial['nucleotides']) < len(full['nucleotides'])
    check(result)
    ligated = client.post('/api/design/forced-ligation', json={
        'three_prime_strand_id': a['id'], 'five_prime_strand_id': b['id'],
    }, headers={'X-NADOC-Skip-Geometry': '1'})
    assert ligated.status_code == 201, ligated.text
    check(ligated.json())
