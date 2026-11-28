"""Selected part history changes share native evaluation and assembly publication."""
import pytest
from fastapi import HTTPException

from backend.api import assembly_state, state, assembly_evaluation_jobs as jobs
from backend.api.assembly import (extrude_instance_overhang, patch_instance_overhang,
    InstanceOverhangPatchRequest, patch_instance, PatchInstanceRequest)
from backend.api.assembly_history_verification import verify
from backend.core.models import Assembly
from tests.test_assembly_instance_recording import authored
from tests.test_assembly_evaluation_jobs import immediate  # noqa: F401


pytestmark = pytest.mark.usefixtures("immediate")


@pytest.fixture(autouse=True)
def sessions():
    state.close_session(); assembly_state.close_session()
    yield
    state.close_session(); assembly_state.close_session()
    with jobs._lock:
        jobs._jobs.clear()


def recipe():
    iid, body = authored()
    extrude_instance_overhang(iid, body)
    oid = assembly_state.get_or_404().instances[0].source.design.overhangs[-1].id
    for label in ('Earlier label', 'Later label'):
        patch_instance_overhang(iid, oid, InstanceOverhangPatchRequest(label=label))
    return assembly_state.get_or_404().model_copy(deep=True)


def change_request(source, operation, index, **kwargs):
    instance = source.instances[0]
    design = instance.source.design
    return {'operation': 'instance-history', 'expected_assembly_id': source.id,
        'expected_revision': assembly_state.revision(), 'instance_id': instance.id,
        'instance_change': {'operation': operation, 'design_id': design.id,
            'feature_id': design.feature_log[index].id, **kwargs}}


@pytest.mark.parametrize('operation,index,options', [
    ('edit', 1, {'params': {'length_bp': 10}}),
    ('suppress', 3, {'suppressed': True}),
    ('delete', 3, {}),
    ('reorder', 2, {'destination': 3}),
])
def test_native_instance_history_commit_reopen_proof_and_undo(operation, index, options):
    source = recipe()
    part_before = state.get_or_404().model_copy(deep=True)
    depth, revision = assembly_state.undo_depth(), assembly_state.revision()
    identity = jobs.start(change_request(source, operation, index, **options))['job_id']
    result = jobs.inspect(identity)['result']
    assert result['status'] == 'ready', result
    assert assembly_state.get_or_404() == source
    assert state.get_or_404() == part_before
    jobs.commit(identity)
    saved = Assembly.from_json(assembly_state.get_or_404().to_json())
    assert len(saved.feature_log) == len(source.feature_log) + 1
    assert saved.feature_log[-1].op_kind == 'assembly-instance-history-change'
    design = saved.instances[0].source.design
    if operation == 'edit':
        assert design.feature_log[1].params['length_bp'] == 10
        assert design.overhangs[-1].label == 'Later label'
    else:
        assert design.overhangs[-1].label == 'Earlier label'
    if operation == 'suppress':
        assert design.feature_log[3].suppressed
    if operation == 'delete':
        assert len(design.feature_log) == 3
    if operation == 'reorder':
        assert design.feature_log[3].id == source.instances[0].source.design.feature_log[2].id
    proof = verify(saved)
    assert proof['status'] == 'verified', proof
    assert assembly_state.undo_depth() == depth + 1
    assert assembly_state.revision() == revision + 1
    assert assembly_state.undo() == source
    assert assembly_state.redo() == saved


def test_editing_instance_history_command_replays_later_assembly_operations():
    source = recipe()
    jobs.commit(jobs.start(change_request(source, 'edit', 1, params={'length_bp': 10}))['job_id'])
    edited = assembly_state.get_or_404().feature_log[-1].id
    patch_instance(source.instances[0].id, PatchInstanceRequest(name='Later assembly name'))
    source = assembly_state.get_or_404().model_copy(deep=True)
    identity = jobs.start({'operation': 'edit', 'expected_assembly_id': source.id,
        'expected_revision': assembly_state.revision(), 'feature_id': edited,
        'inputs': {'params': {'length_bp': 12}}})['job_id']
    result = jobs.inspect(identity)['result']
    assert result['status'] == 'ready', result
    jobs.commit(identity)
    candidate = assembly_state.get_or_404()
    assert candidate.instances[0].name == 'Later assembly name'
    assert candidate.instances[0].source.design.feature_log[1].params['length_bp'] == 12
    assert candidate.instances[0].source.design.overhangs[-1].label == 'Later label'
    assert verify(Assembly.from_json(candidate.to_json()))['status'] == 'verified'


@pytest.mark.parametrize('failure', ['dependent_delete', 'wrong_design', 'missing_feature', 'cancel', 'stale'])
def test_failed_instance_history_change_never_publishes(failure):
    source = recipe()
    request = change_request(source, 'edit', 1, params={'length_bp': 10})
    if failure == 'dependent_delete':
        request = change_request(source, 'delete', 1)
    elif failure == 'wrong_design':
        request['instance_change']['design_id'] = 'other'
    elif failure == 'missing_feature':
        request['instance_change']['feature_id'] = 'missing'
    identity = jobs.start(request)['job_id']
    if failure == 'cancel':
        jobs.inspect(identity, cancel=True)
    elif failure == 'stale':
        patch_instance(source.instances[0].id, PatchInstanceRequest(name='Newer edit'))
    before = assembly_state.get_or_404().model_copy(deep=True)
    depth, revision = assembly_state.undo_depth(), assembly_state.revision()
    with pytest.raises(HTTPException):
        jobs.commit(identity)
    assert assembly_state.get_or_404() == before
    assert (assembly_state.undo_depth(), assembly_state.revision()) == (depth, revision)
