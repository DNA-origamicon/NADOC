"""History actions regenerate chronological member motion, including its dependencies."""
import numpy as np
import pytest
from fastapi import HTTPException
from scipy.spatial.transform import Rotation

from backend.api import crud, part_proof_commands as commands
from backend.api.part_history_reorder import prepare_reorder
from backend.api.part_history_suppression import prepare_suppression
from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from tests.test_part_member_motion_order import D, M, N, _rigid
from tools.member_motion_native_example import build, verify


@pytest.fixture(scope='module')
def source():
    example = build()
    return crud._seek_feature_log(example, 5).copy_with(
        feature_log=example.feature_log[:6], feature_log_cursor=-1, animations=[])


def action(source, kind, index, value):
    prepare = prepare_reorder if kind == 'reorder' else prepare_suppression
    return prepare(source, index, value, executor=commands.execute,
                   dependency_resolver=commands.dependencies)[0]


def assert_motion(source, actual, individual_path, group_path):
    """All native sites and atoms against independent rigid arithmetic from F2."""
    start = crud._seek_feature_log(source, 1)
    hid = start.helices[0].id

    def path(h, bp, direction):
        if h != hid or direction != 'FORWARD' or bp > 3:
            return []
        return individual_path if bp == 3 else group_path

    def moved(value, moves, *, vector=False):
        for move in moves:
            value = Rotation.from_quat(move['rotation']).apply(value) if vector else _rigid(value, move)
        return value

    key = lambda n: (n['strand_id'], n['bp_index'], n['direction'], n.get('copy_k', 0))
    rows = {key(n): n for n in _geometry_for_design(actual)}
    original_rows = _geometry_for_design(start)
    assert set(rows) == {key(n) for n in original_rows}
    for original in original_rows:
        moves = path(original['helix_id'], original['bp_index'], original['direction'])
        for field in ('base_position', 'backbone_position', 'slab_position', 'base_normal', 'axis_tangent'):
            expected = moved(original[field], moves, vector=field in ('base_normal', 'axis_tangent'))
            np.testing.assert_allclose(rows[key(original)][field], expected, atol=1e-10, rtol=0)
    key_atom = lambda a: (a.strand_id, a.bp_index, a.direction, a.copy_k, a.name)
    before = build_atomistic_model(start, fast_bridges=True)
    after = build_atomistic_model(actual, fast_bridges=True)
    atoms = {key_atom(a): a for a in after.atoms}
    assert set(atoms) == {key_atom(a) for a in before.atoms}
    assert after.bonds == before.bonds
    for original in before.atoms:
        atom = atoms[key_atom(original)]
        expected = moved([original.x, original.y, original.z],
                         path(original.helix_id, original.bp_index, original.direction))
        np.testing.assert_allclose([atom.x, atom.y, atom.z], expected, atol=1e-10, rtol=0)


def test_reorder_member_delta_before_cluster_move_changes_chronology(source):
    before = source.model_dump_json()
    candidate = action(source, 'reorder', 5, 4)
    assert [row.id for row in candidate.feature_log] == [source.feature_log[i].id for i in [0, 1, 2, 3, 5, 4]]
    assert_motion(source, candidate, [N, D, M], [M])
    assert _geometry_for_design(candidate) != _geometry_for_design(source)
    verify(Design.from_json(candidate.to_json()))
    restored = action(candidate, 'reorder', 4, 5)
    assert _geometry_for_design(restored) == _geometry_for_design(source)
    assert source.model_dump_json() == before


@pytest.mark.parametrize('index,individual,group', [(2, [M, D], [M]), (4, [N, D], []), (5, [N, M], [M])])
def test_suppress_motion_rebuilds_suffix_and_unsuppress_restores_exactly(source, index, individual, group):
    before = source.model_dump_json()
    candidate = action(source, 'suppress', index, True)
    assert [row.id for row in candidate.feature_log] == [row.id for row in source.feature_log]
    assert candidate.feature_log[index].suppressed
    assert_motion(source, candidate, individual, group)
    reopened = Design.from_json(candidate.to_json())
    verify(reopened)
    restored = action(reopened, 'suppress', index, False)
    verify(restored)
    assert _geometry_for_design(restored) == _geometry_for_design(source)
    assert build_atomistic_model(restored, fast_bridges=True) == build_atomistic_model(source, fast_bridges=True)
    assert source.model_dump_json() == before


@pytest.mark.parametrize('kind,index,value', [('reorder', 3, 4), ('suppress', 3, True)])
def test_cluster_producer_cannot_be_removed_before_its_move(source, kind, index, value):
    before = source.model_dump_json()
    with pytest.raises(HTTPException) as caught:
        action(source, kind, index, value)
    assert caught.value.status_code == 409
    assert caught.value.detail['feature_id'] == source.feature_log[4].id
    assert 'cannot regenerate' in caught.value.detail['detail']
    assert source.model_dump_json() == before
