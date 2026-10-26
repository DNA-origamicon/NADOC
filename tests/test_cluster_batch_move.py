"""Ordinary multi-cluster moves have one replayable, failure-atomic publication."""
from copy import deepcopy

import pytest
from fastapi import HTTPException
from backend.api import state
from backend.api.part_cluster_batch import move_clusters
from backend.api.routes_clusters import ClusterPoseItem
from backend.core.models import Design
from tests.test_compound_member_chronology import recipe
from tests.test_group_organization_history import _verified
from tests.test_group_organization_recording import document as document, before, unchanged
from backend.core.design_geometry import _geometry_for_design


def setup(document):
    source, params = recipe()
    state.load_design(source)
    items = [ClusterPoseItem(cluster_id=p['cluster_id'], fields={k: deepcopy(p[k])
        for k in ('translation', 'rotation', 'pivot')}) for p in params['poses']]
    return items


@pytest.mark.parametrize('reverse', [False, True])
def test_atomic_move_cold_replay_seek_reload_and_one_undo(document, reverse):
    items = setup(document)
    if reverse:
        items.reverse()
    saved = before(document)
    old = _geometry_for_design(document.design)
    result, _ = move_clusters(items, document.revision)
    assert len(result.feature_log) == len(saved[0].feature_log) + 1
    assert len(document.history) == len(saved[3]) + 1 and document.revision == saved[2] + 1
    assert result.nucleotide_transforms != saved[0].nucleotide_transforms
    assert result.group_organization is None
    _verified(Design.from_json(result.to_json()))
    from backend.api.crud import _seek_feature_log
    assert _geometry_for_design(_seek_feature_log(result, len(result.feature_log) - 1)) == _geometry_for_design(result)
    state.undo()
    assert _geometry_for_design(document.design) == old
    state.redo()
    assert _geometry_for_design(document.design) == _geometry_for_design(result)


@pytest.mark.parametrize('damage', ['stale', 'missing', 'duplicate', 'differential', 'cursor', 'field'])
def test_batch_refusal_preserves_all_owners_history_and_revision(document, damage):
    items = setup(document)
    revision = document.revision
    if damage == 'stale': revision -= 1
    if damage == 'missing': items[1].cluster_id = 'missing'
    if damage == 'duplicate': items[1].cluster_id = items[0].cluster_id
    if damage == 'differential': items[1].fields['translation'][0] += 1
    if damage == 'cursor': document.design = document.design.copy_with(feature_log_cursor=0)
    if damage == 'field': items[0].fields['cluster_id'] = 'injected'
    saved = before(document)
    with pytest.raises(HTTPException):
        move_clusters(items, revision)
    unchanged(document, saved)


def test_single_posed_move_undo_response_includes_unchanged_occupancy_helices(document):
    from tests.test_part_transform_preview import source_recipe
    from backend.api import crud
    from backend.core.validator import validate_design
    source = source_recipe('nucleotide-transform', suffix=False)
    state.load_design(source)
    owner = source.cluster_transforms[0]
    moved, _ = move_clusters([ClusterPoseItem(cluster_id=owner.id, fields={
        'translation': [9, 0, 0], 'rotation': [0, 0, 0.3826834323650898, 0.9238795325112867],
        'pivot': [0, 0, 0]})], document.revision)
    assert moved.strands != source.strands  # explicit separated-staple reclassification
    response = crud._design_replace_response(moved, source, validate_design(source))
    assert not response.get('partial_geometry')
    assert response['nucleotides'] == _geometry_for_design(source)
