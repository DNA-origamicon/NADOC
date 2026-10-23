"""Compound member motion survives the existing preview/history lifecycle."""
from copy import deepcopy
from uuid import UUID

import numpy as np
import pytest
from fastapi import HTTPException

from backend.api import part_deformation_preview_sessions as host, state
from backend.api.part_history_reorder import prepare_reorder
from backend.api.part_history_suppression import prepare_suppression
from backend.api.part_proof_commands import dependencies, execute
from backend.core.atomistic import build_atomistic_model
from backend.core.models import Design
from tests.test_compound_member_chronology import recipe
from tests.test_part_deformation_preview_sessions import cancellation, checkpoint, unchanged
from tests.test_part_transform_preview import FEATURE, snapshot
from tests.test_part_transform_preview_sessions import document, opening, update, verified  # noqa: F401


def history_recipe():
    source, params = recipe()
    source.feature_log = [entry.model_copy(update={'id': 'prior-insert-pose'}) if entry.id == FEATURE else entry
                          for entry in source.feature_log]
    source = snapshot(source, 'placement-poses', params, FEATURE)
    source = snapshot(source, 'extrude-segment', {'cells': [[8, 8]], 'length_bp': 3, 'plane': 'XY',
        'history_seed': str(UUID(int=27123))}, 'later-extrusion')
    return source


def patch(opened, *, differential=False):
    poses = deepcopy(opened['control_context']['inputs']['poses'])
    for index, pose in enumerate(poses):
        pose['translation'][0] += 1 if not differential or index == 0 else 2
    return {'poses': poses}


def test_host_apply_carries_insert_preserves_suffix_and_recovers_exactly(document):  # noqa: F811
    source = history_recipe()
    state.load_design(source)
    before = checkpoint()
    opened = host.prepare(opening(), family='transform')
    changed = patch(opened)
    assert host.evaluate(update(opened, params=changed), family='transform')['candidate'] is not None
    unchanged(before)
    assert host.apply(update(opened, sequence=2, params=changed), family='transform')['status'] == 'applied'
    result = state.get_or_404()
    assert state.undo_depth() == len(before['history']) + 1
    assert [row.id for row in result.feature_log] == [row.id for row in source.feature_log]
    original_helices = {helix.id for helix in source.helices[:2]}
    old_atoms = build_atomistic_model(source, fast_bridges=True)
    new_atoms = build_atomistic_model(result, fast_bridges=True)
    assert old_atoms.bonds == new_atoms.bonds
    for old, new in zip(old_atoms.atoms, new_atoms.atoms, strict=True):
        moved = old.helix_id in original_helices or old.extra_base_k is not None
        expected = np.asarray([old.x, old.y, old.z]) + ([1, 0, 0] if moved else [0, 0, 0])
        np.testing.assert_allclose([new.x, new.y, new.z], expected, atol=1e-10, rtol=0)
    reopened = Design.from_json(result.to_json())
    verified(reopened)
    assert build_atomistic_model(reopened, fast_bridges=True) == new_atoms
    state.undo()
    assert state.get_or_404().model_dump(mode='json') == before['json']
    state.redo()
    assert build_atomistic_model(state.get_or_404(), fast_bridges=True) == new_atoms


@pytest.mark.parametrize('operation', ['evaluate', 'apply'])
def test_differential_refusal_keeps_preview_usable_for_corrected_retry(document, operation):  # noqa: F811
    state.load_design(history_recipe())
    before = checkpoint()
    opened = host.prepare(opening(), family='transform')
    with pytest.raises(HTTPException) as caught:
        getattr(host, operation)(update(opened, params=patch(opened, differential=True)), family='transform')
    assert caught.value.status_code == 422
    assert 'Move both ends' in str(caught.value.detail)
    unchanged(before)
    assert host.status(cancellation(opened), family='transform')['status'] == 'ready'
    assert host.evaluate(update(opened, sequence=2, params=patch(opened)), family='transform')['candidate'] is not None
    unchanged(before)
    host.cancel(cancellation(opened), family='transform')
    unchanged(before)


def test_suppress_complete_move_then_unsuppress_restores_insert_and_suffix():
    source = history_recipe()
    before = source.model_dump_json()
    index = next(i for i, row in enumerate(source.feature_log) if row.id == FEATURE)
    candidate, _ = prepare_suppression(source, index, True, executor=execute, dependency_resolver=dependencies)
    verified(candidate)
    restored, _ = prepare_suppression(Design.from_json(candidate.to_json()), index, False,
                                     executor=execute, dependency_resolver=dependencies)
    verified(restored)
    assert build_atomistic_model(restored, fast_bridges=True) == build_atomistic_model(source, fast_bridges=True)
    assert source.model_dump_json() == before


def test_reorder_cannot_move_compound_before_an_owner_producer():
    source = history_recipe()
    before = source.model_dump_json()
    index = next(i for i, row in enumerate(source.feature_log) if row.id == FEATURE)
    with pytest.raises(HTTPException) as caught:
        prepare_reorder(source, index, index - 1, executor=execute, dependency_resolver=dependencies)
    assert caught.value.status_code == 409
    assert caught.value.detail['feature_id'] == FEATURE
    assert source.model_dump_json() == before


def test_undo_response_refreshes_complete_native_member_poses():
    from backend.api import crud
    from backend.core.design_geometry import _geometry_for_design
    from backend.core.validator import validate_design

    source = history_recipe()
    params = deepcopy(next(row.params for row in source.feature_log if row.id == FEATURE))
    for pose in params['poses']:
        pose['translation'][0] += 1
    moved = execute('placement-poses', source, params)
    assert moved.nucleotide_transforms != source.nucleotide_transforms
    for before, after in ((moved, source), (source, moved)):
        response = crud._design_replace_response(before, after, validate_design(after))
        assert response.get('diff_kind') not in {'cluster_only', 'positions_only'}
        assert response['nucleotides'] == _geometry_for_design(after)
