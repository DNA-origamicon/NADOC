"""Display-only seek preparation, revision safety, and unchanged slab authority."""
import json

import numpy as np
import pytest
from fastapi import HTTPException
from scipy.spatial.transform import Rotation

from backend.api import state
from backend.api.doc_context import _current_doc
from backend.api.routes_feature_log import preview_features, seek_features, SeekFeaturesBody
from backend.core.lattice import make_bundle_design
from backend.core.models import SnapshotLogEntry
from backend.core.native_slab_placement import (
    attach_native_slab_poses, _expected_slab_pose,
)


@pytest.fixture
def design():
    pre = make_bundle_design([(0, 0)], length_bp=16)
    post = make_bundle_design([(0, 0), (0, 1)], length_bp=16)
    pre_body, _ = state.encode_design_snapshot(pre)
    post_body, _ = state.encode_design_snapshot(post)
    post.feature_log = [SnapshotLogEntry(op_kind='bundle-create', label='Bundle',
        design_snapshot_gz_b64=pre_body, post_state_gz_b64=post_body)]
    state.load_design(post)
    yield post
    state.close_session()


def preview(position=-2):
    return json.loads(preview_features(SeekFeaturesBody(position=position)).body)


def test_preview_is_read_only_and_commit_reuses_target(design, monkeypatch):
    from backend.api import routes_feature_log as routes
    revision = state.revision()
    prepared = preview()
    assert state.get_or_404() is design
    assert state.revision() == revision
    assert len(prepared['helix_axes']) == 1
    monkeypatch.setattr(routes, '_seek_feature_log', lambda *a, **k: pytest.fail('replayed prepared state'))
    response = seek_features(SeekFeaturesBody(position=-2,
        preview_token=prepared['preview_token'], known_revision=revision))
    payload = json.loads(response.body)
    assert len(state.get_or_404().helices) == 1
    assert payload['feature_log_payloads_partial'] is True
    assert not payload['design']['feature_log'][0]['post_state_gz_b64']
    assert state.get_or_404().feature_log[0].post_state_gz_b64
    state.undo()
    assert len(state.get_or_404().helices) == 2


@pytest.mark.parametrize('change', ['mutation', 'reload', 'wrong_stage', 'other_document', 'consumed'])
def test_stale_or_misbound_preview_cannot_commit(design, change):
    prepared = preview()
    position = -2
    context = None
    if change == 'mutation':
        state.set_design(design.copy_with(feature_log_cursor=0))
    elif change == 'reload':
        state.load_design(design.model_copy(deep=True))
    elif change == 'wrong_stage':
        position = -1
    elif change == 'other_document':
        context = _current_doc.set('other-preview-test')
        state.load_design(design)
    elif change == 'consumed':
        seek_features(SeekFeaturesBody(position=-2, preview_token=prepared['preview_token']))
    before = state.get_or_404()
    try:
        with pytest.raises(HTTPException) as error:
            seek_features(SeekFeaturesBody(position=position, preview_token=prepared['preview_token']))
        assert error.value.status_code == 409
        assert state.get_or_404() is before
    finally:
        if context is not None:
            state.close_session()
            _current_doc.reset(context)


@pytest.mark.parametrize('known', [None, -123])
def test_unknown_client_revision_gets_complete_history(design, known):
    response = seek_features(SeekFeaturesBody(position=-2, known_revision=known))
    payload = json.loads(response.body)
    assert not payload.get('feature_log_payloads_partial')
    assert payload['design']['feature_log'][0]['post_state_gz_b64']


def test_batched_quaternions_match_scalar_authority(design):
    from backend.core.design_geometry import _geometry_for_design
    records = _geometry_for_design(design)
    expected = []
    for record in records:
        center, frame = _expected_slab_pose(record)
        expected.append((center, Rotation.from_matrix(frame).as_quat()))
    attach_native_slab_poses(records)
    for record, (center, quaternion) in zip(records, expected):
        # Batched reductions may differ from scalar arithmetic by a few ULPs.
        # Keep zero relative tolerance and compare every component to the
        # unchanged scalar authority (no geometry golden is regenerated).
        np.testing.assert_allclose(record['slab_position'], center, rtol=0, atol=2e-14)
        np.testing.assert_allclose(record['slab_quaternion'], quaternion, rtol=0, atol=2e-14)


def test_instance_preview_keeps_source_and_assembly_unchanged(design):
    from backend.api import assembly_state
    from backend.api.routes_feature_log import preview_instance_features
    from backend.core.models import Assembly, PartInstance, PartSourceInline, Mat4x4
    transform = Mat4x4(values=[1,0,0,10, 0,1,0,20, 0,0,1,30, 0,0,0,1])
    assembly = Assembly(instances=[PartInstance(id='preview-part',
        source=PartSourceInline(design=design), transform=transform)])
    assembly_state.set_assembly_silent(assembly)
    before = assembly.model_dump()
    try:
        payload = preview_instance_features('preview-part', SeekFeaturesBody(position=-2))
        assert len(payload['helix_axes']) == 1
        assert payload['transform'] == transform.values
        assert assembly_state.get_or_404().model_dump() == before
        assert len(design.helices) == 2
    finally:
        assembly_state.close_session()
