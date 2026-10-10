"""Moving a continued Sweep start cuts its source joins, including history edits."""
import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend.api import state
from backend.api.main import app
from backend.api.crud import _seek_feature_log
from backend.core.models import Design
from backend.core.lattice import make_bundle_design
from backend.core.deformation import deformed_nucleotide_arrays
from backend.core.sweep import SweepRequest, build_sweep


@pytest.mark.parametrize('end', ['start', 'end'])
@pytest.mark.parametrize('later_nick', [False, True])
def test_detach_preserves_source_geometry_and_later_nicks_through_history(end, later_nick):
    original = make_bundle_design([(0,0),(0,1)], 21)
    state.set_design(original)
    client = TestClient(app)
    def post(route, body=None):
        r = client.post('/api/design/' + route, json=body)
        assert r.status_code in (200, 201), r.text
        return r.json()
    sign = 1 if end == 'end' else -1
    p = dict(cells=[[0,0],[0,1]], points_nm=[[0,0,0],[0,0,sign*10]],
             source_helix_id=original.helices[0].id, source_end=end, ligate_adjacent=False)
    post('sweep', p)
    attached = state.get_or_404()
    source_ids = {h.id for h in original.helices}
    swept_ids = {h.id for h in attached.helices} - source_ids
    h = attached.helices[-1]
    if later_nick:
        post('nick', dict(helix_id=h.id, bp_index=h.bp_start+5, direction='FORWARD'))
    old = state.get_or_404()
    p = {**old.feature_log[0].params, 'points_nm': [[4,2,0],[0,0,sign*10]]}
    preview = post('sweep/preview?feature_index=0', p)
    assert preview['source_detached']
    assert state.get_or_404() == old
    post('features/0/edit', {'params': p})
    detached = state.get_or_404()
    def check(d):
        assert d.feature_log[0].params['detach_source']
        for strand in d.strands:
            ids = {dom.helix_id for dom in strand.domains}
            assert not (ids & source_ids and ids & swept_ids)
        for h in original.helices:
            np.testing.assert_allclose(deformed_nucleotide_arrays(d.find_helix(h.id), d)['positions'],
                                       deformed_nucleotide_arrays(h, original)['positions'], atol=1e-9)
    check(detached)
    assert len(detached.strands) == len(old.strands) + len(original.strands)
    loaded = Design.model_validate_json(detached.model_dump_json())
    check(_seek_feature_log(loaded, -1))
    check(_seek_feature_log(loaded, 0))
    post('undo'); assert state.get_or_404().strands == old.strands
    post('redo'); check(state.get_or_404())
    # Detachment remains explicit even if the origin later returns to zero.
    again = {**state.get_or_404().feature_log[0].params, 'points_nm': [[0,0,0],[0,0,sign*10]]}
    post('features/0/edit', {'params': again}); check(state.get_or_404())


def test_new_sweep_with_offset_source_start_splits_sequences_at_the_join():
    original = make_bundle_design([(0,0)], 21)
    original = original.copy_with(strands=[s.model_copy(update={'sequence': 'A'*21}) for s in original.strands])
    body = SweepRequest(cells=[(0,0)], points_nm=[(4,0,0),(0,0,10)],
                        source_helix_id=original.helices[0].id, ligate_adjacent=False)
    result = build_sweep(original, body)
    source = original.helices[0].id
    source_strands = [s for s in result.strands if s.domains[0].helix_id == source]
    assert len(result.strands) == 4
    assert all(len(s.domains) == 1 for s in result.strands)
    assert all(s.sequence == 'A'*21 for s in source_strands)


def test_detached_child_sweep_no_longer_follows_its_source_sweep_edit():
    state.set_design(Design())
    client = TestClient(app)
    def post(route, body):
        r = client.post('/api/design/' + route, json=body)
        assert r.status_code in (200, 201), r.text
    post('sweep', dict(cells=[[0,0]], points_nm=[[0,0,0],[0,0,10]], ligate_adjacent=False))
    parent = state.get_or_404().helices[0].id
    post('sweep', dict(cells=[[0,0]], points_nm=[[0,0,0],[0,0,10]], source_helix_id=parent, ligate_adjacent=False))
    d = state.get_or_404()
    child = d.helices[-1].id
    post('features/1/edit', {'params': {**d.feature_log[1].params, 'points_nm': [[4,0,0],[0,0,10]]}})
    d = state.get_or_404()
    fixed = deformed_nucleotide_arrays(d.find_helix(child), d)['positions']
    post('features/0/edit', {'params': {**d.feature_log[0].params, 'points_nm': [[0,0,0],[8,0,14]]}})
    d = state.get_or_404()
    np.testing.assert_allclose(deformed_nucleotide_arrays(d.find_helix(child), d)['positions'], fixed, atol=1e-9)
