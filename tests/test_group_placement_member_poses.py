"""Grouped placement Apply retains chronological member poses atomically."""
from copy import deepcopy

import numpy as np
import pytest
from fastapi import HTTPException

from backend.api import state
from backend.core.atomistic import build_atomistic_model
from backend.core.models import Design
from tests.test_compound_member_chronology import recipe
from tests.test_group_organization_history import _verified
from tests.test_group_organization_recording import document as document, apply, before, unchanged
from tests.test_part_member_motion_order import M, _rigid
from tests.test_part_transform_preview import source_recipe


def test_single_placement_publishes_carried_residue_pose(document):
    state.load_design(source_recipe('nucleotide-transform', suffix=False))
    apply(document)
    source = document.design
    source_json = source.model_dump_json()
    owner = source.cluster_transforms[0]
    candidate, _, entry = apply(document, 'placement-update', {
        'placement_id': owner.id, 'fields': deepcopy(M)})
    assert candidate.nucleotide_transforms != source.nucleotide_transforms
    assert entry.op_kind == 'placement-poses'
    _verified(candidate)
    from backend.api.crud import _seek_feature_log
    assert build_atomistic_model(_seek_feature_log(candidate, len(candidate.feature_log) - 1),
                                 fast_bridges=True) == build_atomistic_model(candidate, fast_bridges=True)
    old = build_atomistic_model(source, fast_bridges=True)
    new = build_atomistic_model(candidate, fast_bridges=True)
    assert old.bonds == new.bonds
    for a, b in zip(old.atoms, new.atoms, strict=True):
        np.testing.assert_allclose([b.x, b.y, b.z], _rigid([a.x, a.y, a.z], M), atol=1e-10, rtol=0)
    assert source.model_dump_json() == source_json
    state.undo()
    assert document.design.model_dump_json() == source_json
    state.redo()
    assert build_atomistic_model(document.design, fast_bridges=True) == new


@pytest.mark.parametrize('reverse', [False, True])
def test_complete_placement_move_carries_insert_once_and_records_one_feature(document, reverse):
    source, params = recipe()
    state.load_design(source)
    apply(document)
    source = document.design
    saved = before(document)
    placements = [{'placement_id': p['cluster_id'], 'fields': {k: deepcopy(p[k])
                   for k in ('translation', 'rotation', 'pivot')}} for p in params['poses']]
    if reverse:
        placements.reverse()
    candidate, _, entry = apply(document, 'placements-update', {'placements': placements})
    assert len(candidate.feature_log) == len(source.feature_log) + 1
    assert entry.op_kind == 'placement-poses'
    assert document.revision == saved[2] + 1 and len(document.history) == len(saved[3]) + 1
    old = build_atomistic_model(source, fast_bridges=True)
    new = build_atomistic_model(candidate, fast_bridges=True)
    assert old.bonds == new.bonds
    for a, b in zip(old.atoms, new.atoms, strict=True):
        np.testing.assert_allclose([b.x, b.y, b.z], _rigid([a.x, a.y, a.z], M), atol=1e-10, rtol=0)
    from backend.api.crud import _seek_feature_log
    assert build_atomistic_model(_seek_feature_log(candidate, len(candidate.feature_log) - 1), fast_bridges=True) == new
    assert build_atomistic_model(_seek_feature_log(candidate, len(source.feature_log) - 1), fast_bridges=True) == old
    loaded = Design.from_json(candidate.to_json())
    _verified(loaded)
    assert build_atomistic_model(loaded, fast_bridges=True) == new
    state.undo()
    assert document.design.model_dump_json() == saved[1]
    state.redo()
    assert build_atomistic_model(document.design, fast_bridges=True) == new


def test_differential_placement_move_refuses_before_publication(document):
    source, _ = recipe()
    state.load_design(source)
    apply(document)
    saved = before(document)
    with pytest.raises(HTTPException, match='Move both ends'):
        apply(document, 'placements-update', {'placements': [
            {'placement_id': 'arm-0', 'fields': deepcopy(M)}]})
    unchanged(document, saved)
