"""A cluster move carries its members from their current, already-posed state."""
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.api import crud, part_proof_commands as commands
from backend.api.part_group_recording import prepare_group_update
from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from tests.test_part_member_motion_order import D, M, N, _rigid
from tools.member_motion_native_example import build, verify


@pytest.fixture(scope='module')
def example():
    return build()


def test_five_step_cluster_move_carries_previously_moved_base(example):
    before, after = (crud._seek_feature_log(example, i) for i in (3, 4))
    hid = before.helices[0].id
    def selected(n):
        return n['helix_id'] == hid and n['direction'] == 'FORWARD' and n['bp_index'] <= 3
    # Compare by strand identity because OH1 growth relocates staple addresses.
    key = lambda n: (n['strand_id'], n['bp_index'], n['direction'], n.get('copy_k', 0))
    after_by_key = {key(n): n for n in _geometry_for_design(after)}
    rotation = Rotation.from_quat(M['rotation'])
    for old in _geometry_for_design(before):
        new = after_by_key[key(old)]
        for field in ('base_position', 'backbone_position', 'slab_position'):
            expected = _rigid(old[field], M) if selected(old) else old[field]
            np.testing.assert_allclose(new[field], expected, atol=1e-10, rtol=0)
        for field in ('base_normal', 'axis_tangent'):
            expected = rotation.apply(old[field]) if selected(old) else old[field]
            np.testing.assert_allclose(new[field], expected, atol=1e-10, rtol=0)
    old_atoms = build_atomistic_model(before, fast_bridges=True)
    new_atoms = build_atomistic_model(after, fast_bridges=True)
    key_atom = lambda a: (a.strand_id, a.bp_index, a.direction, a.copy_k, a.name)
    new_by_key = {key_atom(a): a for a in new_atoms.atoms}
    for old in old_atoms.atoms:
        new = new_by_key[key_atom(old)]
        moved = old.helix_id == hid and old.direction == 'FORWARD' and old.bp_index <= 3
        xyz = [old.x, old.y, old.z]
        np.testing.assert_allclose([new.x, new.y, new.z], _rigid(xyz, M) if moved else xyz,
                                  atol=1e-10, rtol=0)


def test_later_base_delta_then_another_cluster_move_replays_in_order(example):
    source = crud._seek_feature_log(example, 5).copy_with(feature_log=example.feature_log[:6], feature_log_cursor=-1)
    # F6 already adds D to the individually posed base, after the first cluster move.
    prior = crud._seek_feature_log(example, 4)
    hid = source.helices[0].id
    def target(design):
        return next(n for n in _geometry_for_design(design) if n['helix_id'] == hid
                    and n['bp_index'] == 3 and n['direction'] == 'FORWARD')
    np.testing.assert_allclose(target(source)['base_position'], _rigid(target(prior)['base_position'], D), atol=1e-10)
    current = source.cluster_transforms[-1]
    translation = np.asarray(current.translation) + [2, -1, 3]
    after, _ = prepare_group_update(source, current.id, {'translation': translation.tolist()})
    np.testing.assert_allclose(target(after)['base_position'], np.asarray(target(source)['base_position']) + [2, -1, 3], atol=1e-10)
    assert after.feature_log[-1].op_kind == 'placement-poses'
    verify(Design.from_json(after.to_json()))
    for index, expected in ((5, source), (6, after), (5, source), (-1, after)):
        assert _geometry_for_design(crud._seek_feature_log(after, index)) == _geometry_for_design(expected)


def test_pose_transport_does_not_mutate_source_and_repeated_absolute_pose_is_noop(example):
    source = crud._seek_feature_log(example, 4).copy_with(feature_log=example.feature_log[:5], feature_log_cursor=-1)
    captured = source.model_dump_json()
    c = next(c for c in source.cluster_transforms if c.id == 'first-group-move')
    after = commands.execute('cluster_op', source, {'_proof_version': 1, 'cluster_id': c.id,
        'rotation': c.rotation, 'translation': c.translation, 'pivot': c.pivot})
    assert after.nucleotide_transforms == source.nucleotide_transforms
    assert _geometry_for_design(after) == _geometry_for_design(source)
    assert source.model_dump_json() == captured


def test_commit_after_live_pose_preview_keeps_complete_scrub_state(example):
    source = crud._seek_feature_log(example, 4).copy_with(feature_log=example.feature_log[:5], feature_log_cursor=-1)
    owner = next(c for c in source.cluster_transforms if c.id == 'first-group-move')
    fields = {'translation': (np.asarray(owner.translation) + [2, 3, 4]).tolist()}
    preview = commands.execute('cluster_op', source, {'_proof_version': 1, 'cluster_id': owner.id, **fields})
    committed, entry = prepare_group_update(preview, owner.id, fields)
    assert entry.op_kind == 'placement-poses'
    verify(Design.from_json(committed.to_json()))
    assert _geometry_for_design(crud._seek_feature_log(committed, 5)) == _geometry_for_design(preview)


@pytest.mark.parametrize('end', ['five_prime', 'three_prime'])
def test_cluster_carries_individually_posed_terminal_tail(end):
    from backend.core.models import ClusterRigidTransform, Direction, NucleotideTransform
    from tools.member_motion_tail_audit import tail_source
    from tests.test_part_member_motion_order import N
    source, address = tail_source(end, Direction.FORWARD, 0)
    source = source.copy_with(cluster_transforms=[ClusterRigidTransform(id='tail-owner', helix_ids=[address[0]])],
        nucleotide_transforms=[NucleotideTransform(kind='base', helix_id='__ext_selected-tail',
            bp_index=1, direction=Direction.FORWARD, **N)])
    after = commands.execute('cluster_op', source, {'_proof_version': 1, 'cluster_id': 'tail-owner', **M})
    for old, new in zip(_geometry_for_design(source), _geometry_for_design(after), strict=True):
        selected = old['helix_id'] == address[0] or old.get('extension_id') in {'selected-tail', 'control-tail'}
        for field in ('base_position', 'backbone_position'):
            np.testing.assert_allclose(new[field], _rigid(old[field], M) if selected else old[field], atol=1e-10, rtol=0)


def test_cluster_carries_posed_crossover_insert_when_both_ends_move():
    from backend.core.models import ClusterRigidTransform
    from tests.test_part_transform_preview import source_recipe
    source = source_recipe('nucleotide-transform', extra=True, suffix=False)
    source = source.copy_with(cluster_transforms=[ClusterRigidTransform(id='insert-owner',
        helix_ids=[h.id for h in source.helices])])
    before = build_atomistic_model(source, fast_bridges=True)
    after = commands.execute('cluster_op', source, {'_proof_version': 1, 'cluster_id': 'insert-owner', **M})
    atoms = build_atomistic_model(after, fast_bridges=True)
    assert any(a.extra_base_k is not None for a in before.atoms)
    for old, new in zip(before.atoms, atoms.atoms, strict=True):
        np.testing.assert_allclose([new.x, new.y, new.z], _rigid([old.x, old.y, old.z], M), atol=1e-10, rtol=0)


@pytest.mark.parametrize('index', range(2, 11), ids=[f'F{i}' for i in range(3, 12)])
def test_original_sequence_matches_chronological_coordinates_at_every_step(example, index):
    replacement = dict(rotation=Rotation.from_euler('y', 37, degrees=True).as_quat().tolist(),
        pivot=[-2, 3, .7], translation=[1, 2, -.5])
    second_move = dict(rotation=Rotation.from_euler('x', -25, degrees=True).as_quat().tolist(),
        pivot=[1, -.5, .3], translation=[.4, -.2, .6])
    # Explicit chronological paths, independent of the native pose evaluator.
    # Reset drops the earlier individual edits N and D, retaining the first M.
    base_three_paths = {2: [N], 3: [N], 4: [N, M], 5: [N, M, D],
        6: [M], 7: [M, replacement], 8: [M, replacement],
        9: [M, replacement, second_move], 10: [M, replacement, second_move, D]}
    start = crud._seek_feature_log(example, 1)
    actual = crud._seek_feature_log(example, index)
    hid = start.helices[0].id
    def path(h, bp, direction):
        if h != hid or direction != 'FORWARD' or bp > 3:
            return []
        if bp == 3:
            return base_three_paths[index]
        return ([M] if index >= 4 else []) + ([second_move] if index >= 9 else [])
    def point(value, moves):
        for move in moves:
            value = _rigid(value, move)
        return value
    key = lambda n: (n['strand_id'], n['bp_index'], n['direction'], n.get('copy_k', 0))
    actual_rows = {key(n): n for n in _geometry_for_design(actual)}
    largest = 0.0
    for original in _geometry_for_design(start):
        row = actual_rows[key(original)]
        moves = path(original['helix_id'], original['bp_index'], original['direction'])
        for field in ('base_position', 'backbone_position', 'slab_position'):
            expected = point(original[field], moves)
            largest = max(largest, float(np.linalg.norm(np.asarray(row[field]) - expected)))
            np.testing.assert_allclose(row[field], expected, atol=1e-10, rtol=0)
        for field in ('base_normal', 'axis_tangent'):
            expected = original[field]
            for move in moves:
                expected = Rotation.from_quat(move['rotation']).apply(expected)
            np.testing.assert_allclose(row[field], expected, atol=1e-10, rtol=0)
    key_atom = lambda a: (a.strand_id, a.bp_index, a.direction, a.copy_k, a.name)
    actual_atoms = {key_atom(a): a for a in build_atomistic_model(actual, fast_bridges=True).atoms}
    for original in build_atomistic_model(start, fast_bridges=True).atoms:
        atom = actual_atoms[key_atom(original)]
        expected = point([original.x, original.y, original.z],
            path(original.helix_id, original.bp_index, original.direction))
        largest = max(largest, float(np.linalg.norm(np.asarray([atom.x, atom.y, atom.z]) - expected)))
        np.testing.assert_allclose([atom.x, atom.y, atom.z], expected, atol=1e-10, rtol=0)
    print(f'F{index + 1}: largest chronological position discrepancy = {largest:.3g} nm')
