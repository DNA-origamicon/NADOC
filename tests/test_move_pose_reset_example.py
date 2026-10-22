"""Reset only the base pose after a cluster move and overhang reclassification."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import crud, state
from backend.api.main import app
from backend.core.atomistic import build_atomistic_model
from backend.core.deformation import deformed_helix_axes
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from tools.member_motion_native_example import build, verify
from tools.member_motion_reset_example import build as reset_example
from tests.test_part_member_motion_order import M, _rigid


@pytest.fixture(scope='module')
def example():
    return reset_example(build())


def test_reset_retains_cluster_motion_and_only_moves_base_three(example):
    before = crud._seek_feature_log(example, 4)
    original = crud._seek_feature_log(example, 1)
    after = Design.from_json(example.to_json())
    verify(after)
    assert not after.nucleotide_transforms
    assert after.cluster_transforms == before.cluster_transforms
    assert after.overhangs == before.overhangs
    assert after.overhangs[0].label == 'OH1'
    assert after.overhangs[0].sub_domains[0].length_bp == 4
    assert after.strands == before.strands
    hid = after.helices[0].id
    def target(site):
        return site['helix_id'] == hid and site['bp_index'] == 3 and site['direction'] == 'FORWARD'
    original_site = next(site for site in _geometry_for_design(original) if target(site))
    changed = 0
    for old, new in zip(_geometry_for_design(before), _geometry_for_design(after), strict=True):
        if target(new):
            for field in ('base_position', 'backbone_position', 'slab_position'):
                np.testing.assert_allclose(new[field], _rigid(original_site[field], M), atol=1e-10, rtol=0)
            assert old['base_position'] != new['base_position']
            changed += 1
        else:
            assert old == new
    assert changed == 1
    atoms_before = build_atomistic_model(before, fast_bridges=True)
    atoms_after = build_atomistic_model(after, fast_bridges=True)
    assert atoms_before.bonds == atoms_after.bonds
    for old, new in zip(atoms_before.atoms, atoms_after.atoms, strict=True):
        if not (new.helix_id == hid and new.bp_index == 3 and new.direction == 'FORWARD'):
            assert old == new
    axis = next(a for a in deformed_helix_axes(after) if a['helix_id'] == hid)
    assert [(s['bp_lo'], s['bp_hi']) for s in axis['segments']] == [(0, 3), (4, 7)]
    for index in (4, 5, 2, 5, 4, -1):
        sought = crud._seek_feature_log(after, index)
        if index in (5, -1):
            assert _geometry_for_design(sought) == _geometry_for_design(example)
        after = sought
    assert [k.feature_log_index for k in example.animations[0].keyframes] == list(range(6))


def test_ordinary_reset_api_undo_redo(example):
    before = crud._seek_feature_log(example, 4).copy_with(
        feature_log=example.feature_log[:5], feature_log_cursor=-1)
    state.load_design(before)
    try:
        with TestClient(app) as client:
            response = client.delete(f'/api/design/nucleotide-transform/{before.nucleotide_transforms[0].id}')
            assert response.status_code == 200, response.text
            actual = state.get_or_404()
            assert len(actual.feature_log) == 6
            assert _geometry_for_design(actual) == _geometry_for_design(example)
            verify(Design.from_json(actual.to_json()))
            assert client.post('/api/design/undo').status_code == 200
            assert _geometry_for_design(state.get_or_404()) == _geometry_for_design(before)
            assert client.post('/api/design/redo').status_code == 200
            assert _geometry_for_design(state.get_or_404()) == _geometry_for_design(example)
    finally:
        state.close_session()
