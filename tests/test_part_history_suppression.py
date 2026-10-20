"""Suppression retains authored recipes while omitting their execution."""
import pytest
from fastapi import HTTPException

from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history
from tests.test_part_history_reorder import native_source, scoped_deformation_source
from tests.test_part_sweep_preview import source_recipe


def change(source, index, suppressed):
    from backend.api.part_history_suppression import prepare_suppression
    return prepare_suppression(source, index, suppressed,
        executor=execute, dependency_resolver=dependencies)[0]


def proof(source):
    result = assess_part_history(source, execute=execute, dependencies=dependencies)
    assert result['status'] in {'verified', 'reproduced_import'}, result
    return result


@pytest.mark.parametrize('kind', ['bend', 'twist', 'sweep', 'extrude', 'routing'])
def test_suppress_reopen_unsuppress_reproduces_original_authoring(kind):
    if kind in {'bend', 'twist'}:
        source = scoped_deformation_source(kind, 'twist')
        index = 3
    elif kind in {'sweep', 'extrude'}:
        source = source_recipe()
        index = 1 if kind == 'sweep' else 2
    else:
        source, index = native_source(), 0
    before = source.model_dump(mode='json')
    original = proof(source)
    candidate = change(source, index, True)
    assert candidate.feature_log[index].suppressed is True
    assert [row.id for row in candidate.feature_log] == [row.id for row in source.feature_log]
    assert proof(candidate)['recipe_fingerprint'] != original['recipe_fingerprint']
    reopened = Design.model_validate_json(candidate.model_dump_json())
    proof(reopened)
    restored = change(reopened, index, False)
    assert proof(restored)['authoring_fingerprint'] == original['authoring_fingerprint']
    assert proof(restored)['recipe_fingerprint'] == original['recipe_fingerprint']
    assert source.model_dump(mode='json') == before


def test_suppress_missing_producer_refuses_without_removing_fine_routing_children():
    from backend.core.models import MinorMutationLogEntry, RoutingClusterLogEntry
    source = native_source()
    params = {'joint_id': 'a', 'name': 'Dependent', '_proof_version': 1}
    log = list(source.feature_log)
    source = execute('joint-update', source, params)
    source.feature_log = log + [RoutingClusterLogEntry(id='dependent', children=[
        MinorMutationLogEntry(id='dependent-child', op_subtype='joint-update', label='Dependent', params=params)])]
    before = source.model_dump()
    with pytest.raises(HTTPException) as caught:
        change(source, 0, True)
    assert caught.value.status_code == 409
    assert caught.value.detail['feature_id'] == 'dependent-child'
    assert 'F4 Dependent' in caught.value.detail['detail']
    assert source.model_dump() == before


def test_suppressed_overlay_survives_rollback_and_prefix_capture():
    from backend.api.crud import _seek_feature_log
    from backend.core.part_verification_capture import capture
    source = scoped_deformation_source()
    candidate = change(source, 3, True)
    for preserve in [False, True]:
        captured = capture(candidate, preserve_entry_types=preserve)
        proof(captured)
    rolled = _seek_feature_log(candidate, 3)
    assert not rolled.deformations
    resumed = _seek_feature_log(rolled, -1)
    assert resumed.deformations == candidate.deformations
    assert resumed.feature_log[3].suppressed
    proof(resumed)


@pytest.mark.parametrize('outcome', ['commit', 'cancel', 'stale'])
def test_suppression_uses_existing_publication_and_undo(monkeypatch, outcome):
    from backend.api import part_evaluation_jobs as jobs, state
    from backend.api.part_evaluation import evaluate
    from backend.api.doc_context import set_current_doc, reset_current_doc

    class Worker:
        def __init__(self, source, operation):
            self.source, self.operation = source, operation
        def start(self):
            pass
        def wait(self, timeout):
            return True
        def result(self):
            return evaluate(self.source, self.operation)
        def close(self):
            pass

    monkeypatch.setattr(jobs, 'EvaluationWorker', Worker)
    monkeypatch.setattr(jobs, '_submit', jobs._run)
    token = set_current_doc('history-suppression-test')
    identity = None
    try:
        state.load_design(native_source())
        source, revision = state.get_design_with_revision()
        depth = state.undo_depth()
        identity = jobs.start({'operation': 'suppress', 'index': 0, 'suppressed': True,
                               'expected_revision': revision})['job_id']
        result = jobs.inspect(identity)
        assert result['result']['status'] == 'ready', result
        assert state.get_design_with_revision() == (source, revision)
        if outcome == 'cancel':
            jobs.inspect(identity, cancel=True)
        elif outcome == 'stale':
            state.set_design(source.model_copy(update={'name': 'Changed'}))
        if outcome != 'commit':
            current = state.get_design_with_revision()
            with pytest.raises(HTTPException):
                jobs.commit(identity)
            assert state.get_design_with_revision() == current
            return
        receipt = jobs.commit(identity)
        assert state.get_or_404().feature_log[0].suppressed
        assert state.undo_depth() == depth + 1
        assert jobs.commit(identity)['revision'] == receipt['revision']
        state.undo()
        assert not state.get_or_404().feature_log[0].suppressed
        state.redo()
        assert state.get_or_404().feature_log[0].suppressed
        proof(state.get_or_404())
    finally:
        if identity:
            with jobs._lock:
                jobs._jobs.pop(identity, None)
        state.close_session()
        reset_current_doc(token)


@pytest.mark.parametrize('extra', [{'suppressed': 1}, {'expected_revision': None},
    {'sub_index': 0}, {'destination': 1}, {'params': {}}, {'cascade': True}])
def test_suppression_request_rejects_ambiguous_or_unbound_input(extra):
    from pydantic import ValidationError
    from backend.api.part_evaluation import EvaluationRequest
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate({'operation': 'suppress', 'index': 0,
            'suppressed': True, 'expected_revision': 1, **extra})


def test_disabled_definitions_remain_bound_and_fine_routing_children_keep_identity():
    source = change(native_source(), 0, True)
    original = proof(source)
    child = source.feature_log[0].children[0]
    identity = child.id
    child.params['name'] = 'Saved while suppressed'
    updated = proof(source)
    assert updated['authoring_fingerprint'] == original['authoring_fingerprint']
    assert updated['recipe_fingerprint'] != original['recipe_fingerprint']
    enabled = change(source, 0, False)
    assert enabled.feature_log[0].children[0].id == identity
    assert next(joint for joint in enabled.cluster_joints if joint.id == 'a').name == 'Saved while suppressed'


def test_private_preview_and_reorder_reuse_suppressed_prefix():
    from backend.api.part_history_reorder import prepare_reorder
    from backend.api.part_deformation_preview import prepare_from_capture
    from backend.core.part_verification_capture import capture
    source = change(scoped_deformation_source(), 3, True)
    owner = prepare_from_capture(capture(source, preserve_entry_types=True), 'right-feature')
    assert not owner.copy_prefix().deformations
    moved, _ = prepare_reorder(source, 3, 4, executor=execute, dependency_resolver=dependencies)
    assert moved.feature_log[4].suppressed
    proof(moved)
    restored = change(moved, 4, False)
    assert len(restored.deformations) == 2
    proof(restored)


@pytest.mark.parametrize('kind', ['routing', 'sweep'])
def test_saved_repair_draft_fingerprint_binds_suppression(kind):
    from backend.core.part_repair_capture import capture_draft_inputs
    from backend.core.part_repair_fingerprint import repair_base_fingerprint
    source = native_source() if kind == 'routing' else source_recipe()
    before = repair_base_fingerprint(source)
    candidate = change(source, 0 if kind == 'routing' else 1, True)
    after = repair_base_fingerprint(candidate)
    assert after != before
    assert repair_base_fingerprint(capture_draft_inputs(candidate, source_revision=1)) == after
