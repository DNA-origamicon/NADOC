"""Navigation must remain correct without materialized recovery outputs."""
import pytest
from fastapi import HTTPException

from backend.api import state
from backend.api.crud import BundleRequest, create_bundle, _seek_feature_log, revert_to_before_feature
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.part_history_navigation import revert_recipe
from backend.api.part_proof_commands import dependencies, execute
from backend.core.part_history_contract import assess_part_history
from backend.core.models import Design
from tests.test_part_recipe_edit import document  # noqa: F401


def strip_recovery(source):
    source = source.model_copy(deep=True)
    for row in source.feature_log:
        if row.feature_type == 'snapshot':
            row.design_snapshot_gz_b64 = ''
        elif row.feature_type == 'routing-cluster':
            row.pre_state_gz_b64 = ''
            row.diffs_evicted = True
            for child in row.children:
                child.diff_added_b64 = child.diff_removed_b64 = child.diff_modified_b64 = ''
        else:
            continue
        row.evicted = True
        row.post_state_gz_b64 = ''
    return source


def proof(source):
    result = assess_part_history(source, execute=execute, dependencies=dependencies)
    assert result['status'] == 'verified', result
    return result['authoring_fingerprint']


def test_seek_all_stages_without_recovery_and_return_to_end():
    source = strip_recovery(state.get_or_404())
    expected = proof(source)
    before = source.model_dump_json()
    first = _seek_feature_log(source, -2)
    assert not first.helices and not first.cluster_joints
    assert first.feature_log_cursor == -2
    assert first.feature_log == source.feature_log
    bundle = _seek_feature_log(first, 0)
    assert len(bundle.helices) == 1 and not bundle.cluster_joints
    joint = _seek_feature_log(bundle, 1, 0)
    assert len(joint.cluster_joints) == 1
    assert joint.feature_log_sub_cursor == 0
    before_child = _seek_feature_log(joint, 1, -2)
    assert not before_child.cluster_joints
    end = _seek_feature_log(before_child, -1)
    assert proof(end) == expected
    assert source.model_dump_json() == before


@pytest.mark.parametrize('index,sub_index', [(0, None), (1, None), (1, 0)])
def test_revert_missing_recovery_one_undo_redo_reopen(index, sub_index):
    source = strip_recovery(state.get_or_404())
    state.load_design(source)
    before = source.model_dump_json()
    depth = state.undo_depth()
    revert_to_before_feature(index, sub_index)
    result = state.get_or_404()
    assert len(result.feature_log) == index
    assert not result.cluster_joints
    assert len(result.helices) == index
    assert result.feature_log_cursor == -1 and result.feature_log_sub_cursor is None
    proof(Design.model_validate_json(result.model_dump_json()))
    assert state.undo_depth() == depth + 1
    state.undo()
    assert state.get_or_404().model_dump_json() == before
    state.redo()
    proof(state.get_or_404())


def test_unknown_prefix_refuses_atomically_but_can_revert_before_it():
    source = strip_recovery(state.get_or_404())
    source.feature_log[1].children[0].op_subtype = 'unknown-command'
    state.load_design(source)
    before, revision = state.get_design_with_revision()
    depth = state.undo_depth()
    with pytest.raises(HTTPException) as error:
        _seek_feature_log(before, -1)
    assert error.value.detail['code'] == 'missing_proof_contract'
    assert state.get_design_with_revision() == (before, revision)
    assert state.undo_depth() == depth
    revert_to_before_feature(1)
    proof(state.get_or_404())


def test_revert_rejects_stale_publication(monkeypatch):
    from backend.api import part_history_navigation
    original = part_history_navigation.revert_recipe
    def concurrent(*args):
        candidate = original(*args)
        state.set_design(state.get_or_404().copy_with())
        return candidate
    monkeypatch.setattr(part_history_navigation, 'revert_recipe', concurrent)
    with pytest.raises(HTTPException) as error:
        revert_to_before_feature(0)
    assert error.value.status_code == 409
    assert len(state.get_or_404().feature_log) == 2


def test_revert_replays_inputs_even_with_poisoned_recovery():
    source = state.get_or_404()
    source.feature_log[1].pre_state_gz_b64 = 'not a snapshot'
    revert_to_before_feature(1)
    proof(state.get_or_404())


def test_partial_routing_revert_regenerates_retained_children():
    from backend.api.routes_cluster_joints import _build_add_joint
    source = state.get_or_404()
    params = {**source.feature_log[1].children[0].params, 'joint_id': 'second'}
    state.mutate_with_minor_log(op_subtype='joint-place', label='Second joint', params=params,
        fn=lambda d: _build_add_joint(d, params))
    source = strip_recovery(state.get_or_404())
    assert len(source.feature_log[1].children) == 2
    result = revert_recipe(source, 1, 1)
    assert [j.id for j in result.cluster_joints] == ['joint']
    assert len(result.feature_log[1].children) == 1
    assert not result.feature_log[1].evicted
    proof(result)


def test_new_bundle_f0_regression():
    token = set_current_doc('navigation-f0-regression')
    try:
        create_bundle(BundleRequest(cells=[[0, 0]], length_bp=21))
        source = strip_recovery(state.get_or_404())
        proof(source)
        assert not _seek_feature_log(source, -2).helices
    finally:
        state.close_session()
        reset_current_doc(token)


@pytest.mark.parametrize('payload', ['not base64!', 'bm90IGd6aXA=', 'H4sI'])
def test_corrupt_snapshot_seek_uses_recipe(payload):
    source = state.get_or_404().model_copy(deep=True)
    source.feature_log[0].design_snapshot_gz_b64 = payload
    assert not _seek_feature_log(source, -2).helices


def test_preview_commit_missing_recovery_is_read_only_until_commit():
    import json
    from backend.api.routes_feature_log import preview_features, seek_features, SeekFeaturesBody
    state.load_design(strip_recovery(state.get_or_404()))
    before, revision = state.get_design_with_revision()
    preview = json.loads(preview_features(SeekFeaturesBody(position=-2)).body)
    assert preview['helix_axes'] == []
    assert state.get_design_with_revision() == (before, revision)
    seek_features(SeekFeaturesBody(position=-2, preview_token=preview['preview_token']))
    assert not state.get_or_404().helices
    state.undo()
    assert state.get_or_404() == before


def test_replayed_stage_does_not_inherit_later_atom_reference():
    from backend.core.models import AtomisticReference
    source = strip_recovery(state.get_or_404())
    source.atomistic_reference = AtomisticReference(source='later physical result')
    assert _seek_feature_log(source, -2).atomistic_reference is None
    assert source.atomistic_reference.source == 'later physical result'


def test_missing_child_diffs_replay_even_without_eviction_flag():
    source = state.get_or_404().model_copy(deep=True)
    expected = proof(source)
    row = source.feature_log[1]
    assert not row.diffs_evicted and row.pre_state_gz_b64
    for child in row.children:
        child.diff_added_b64 = child.diff_removed_b64 = child.diff_modified_b64 = ''
    result = _seek_feature_log(source, 1, 0)
    assert result.cluster_joints == source.cluster_joints
    assert proof(_seek_feature_log(result, -1)) == expected


def test_failed_native_command_names_feature_without_publishing():
    source = strip_recovery(state.get_or_404())
    child = source.feature_log[1].children[0]
    child.params['cluster_id'] = 'missing-cluster'
    state.load_design(source)
    before, revision = state.get_design_with_revision()
    with pytest.raises(HTTPException) as error:
        _seek_feature_log(source, -1)
    assert error.value.status_code == 409
    assert error.value.detail['feature_id'] == child.id
    assert state.get_design_with_revision() == (before, revision)
