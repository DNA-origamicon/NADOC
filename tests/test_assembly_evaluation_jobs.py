"""Verified private assembly history candidates and explicit source-bound commit."""
from threading import Event
import pytest
from fastapi import HTTPException

from backend.api import assembly_state, state, assembly_evaluation_jobs as jobs
from backend.api.assembly_evaluation import evaluate
from backend.api.assembly_history_verification import verify
from backend.api.part_history_verification import _slot
from tests.test_assembly_history_verification import recorded


@pytest.fixture(autouse=True)
def sessions():
    assembly_state.close_session()
    state.close_session()
    yield
    assembly_state.close_session()
    state.close_session()
    with jobs._lock:
        jobs._jobs.clear()


@pytest.fixture
def immediate(monkeypatch):
    def submit(job, source, operation):
        try:
            job.result = evaluate(source, operation)
            job.status = 'complete'
        finally:
            _slot.release()
    monkeypatch.setattr(jobs, '_submit', submit)


def request(source, operation='suppress', **changes):
    return {'operation': operation, 'expected_assembly_id': source.id,
            'expected_revision': assembly_state.revision(), 'feature_id': source.feature_log[1].id,
            **({'suppressed': True} if operation == 'suppress' else {}), **changes}


@pytest.mark.parametrize('operation', ['suppress', 'edit', 'delete', 'reorder'])
def test_private_candidate_commit_saved_replay_and_one_undo(immediate, operation):
    from backend.api.assembly import patch_instance, PatchInstanceRequest
    from backend.core.models import Assembly
    source = recorded()
    patch_instance(source.instances[0].id, PatchInstanceRequest(fixed=False))
    source = assembly_state.get_or_404().model_copy(deep=True)
    body = request(source, operation, **({'inputs': {'name': 'Edited'}} if operation == 'edit'
                                      else {'destination': 2} if operation == 'reorder' else {}))
    revision, depth = assembly_state.revision(), assembly_state.undo_depth()
    identity = jobs.start(body)['job_id']
    result = jobs.inspect(identity)
    assert result['result']['status'] == 'ready', result
    assert 'candidate' not in result['result']
    assert assembly_state.get_or_404() == source
    assert assembly_state.undo_depth() == depth
    commit = jobs.commit(identity)
    assert commit['revision'] == revision + 1
    saved = Assembly.from_json(assembly_state.get_or_404().to_json())
    assert verify(saved)['status'] == 'verified'
    if operation == 'suppress':
        assert saved.feature_log[1].suppressed
        assert saved.instances[0].name == 'Part'
    elif operation == 'edit':
        assert saved.instances[0].name == 'Edited'
    elif operation == 'reorder':
        assert saved.feature_log[2].id == source.feature_log[1].id
        assert saved.instances[0].fixed
    else:
        assert len(saved.feature_log) == len(source.feature_log) - 1
    assert assembly_state.undo_depth() == depth + 1
    repeated = jobs.commit(identity)
    assert repeated['revision'] == revision + 1
    assert repeated['assembly_id'] == source.id
    assert assembly_state.undo_depth() == depth + 1
    assert assembly_state.undo() == source
    assert assembly_state.redo() == saved


def test_unsuppression_regenerates_definition(immediate):
    source = recorded()
    identity = jobs.start(request(source))['job_id']
    jobs.commit(identity)
    source = assembly_state.get_or_404().model_copy(deep=True)
    identity = jobs.start(request(source, suppressed=False))['job_id']
    jobs.commit(identity)
    assert assembly_state.get_or_404().instances[0].name == 'Renamed'
    assert verify(assembly_state.get_or_404())['status'] == 'verified'


@pytest.mark.parametrize('failure', ['revision', 'in_place', 'candidate', 'cancel', 'session'])
def test_failed_commit_does_not_publish(immediate, failure):
    source = recorded()
    identity = jobs.start(request(source))['job_id']
    if failure == 'revision':
        assembly_state.set_assembly(source.model_copy(deep=True))
    elif failure == 'in_place':
        assembly_state.get_or_404().metadata.name = 'Untracked change'
    elif failure == 'candidate':
        jobs._jobs[identity].result['candidate']['metadata']['name'] = 'Tampered'
    elif failure == 'cancel':
        jobs.inspect(identity, cancel=True)
    else:
        original = assembly_state.get_or_404()
        assembly_state.close_session()
        assembly_state.load_assembly(original)
    before = assembly_state.get_or_404().model_copy(deep=True)
    revision, depth = assembly_state.revision(), assembly_state.undo_depth()
    with pytest.raises(HTTPException) as error:
        jobs.commit(identity)
    assert error.value.status_code == 409
    assert assembly_state.get_or_404() == before
    assert assembly_state.revision() == revision
    assert assembly_state.undo_depth() == depth


def test_invalid_dependency_order_returns_failure_without_candidate(immediate):
    source = recorded()
    identity = jobs.start(request(source, 'reorder', destination=0))['job_id']
    result = jobs.inspect(identity)['result']
    assert result['status'] == 'failed'
    assert result['issues'][0]['detail']['feature_id'] == source.feature_log[1].id
    with pytest.raises(HTTPException):
        jobs.commit(identity)
    assert assembly_state.get_or_404() == source


def test_actual_spawned_evaluation_and_http_commit(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    source = recorded()
    completed = Event()
    original = jobs._run
    def run(*args):
        try:
            original(*args)
        finally:
            completed.set()
    monkeypatch.setattr(jobs, '_run', run)
    client = TestClient(app)
    response = client.post('/api/assembly/features/evaluation/jobs', json=request(source))
    assert response.status_code == 202, response.text
    path = '/api/assembly/features/evaluation/jobs/' + response.json()['job_id']
    assert completed.wait(20)
    response = client.get(path)
    assert response.json()['result']['status'] == 'ready', response.json()
    assert 'candidate' not in response.json()['result']
    assert client.post(path + '/commit').status_code == 200
    assert assembly_state.get_or_404().instances[0].name == 'Part'


def test_autosave_preserves_source_history_revision_and_ready_candidate(immediate, tmp_path, monkeypatch):
    from backend.api import assembly as routes
    from backend.api.routes_assembly_workspace import save_assembly, SaveAssemblyRequest
    from backend.core.models import Assembly
    source = recorded()
    monkeypatch.setattr(routes, '_WORKSPACE_DIR', tmp_path)
    revision = assembly_state.revision()
    identity = jobs.start(request(source))['job_id']
    assert save_assembly(SaveAssemblyRequest(path='__e2e__save.nass')) == {'path': '__e2e__save.nass'}
    assert assembly_state.revision() == revision
    assert assembly_state.get_or_404() == source
    assert not list(tmp_path.glob('*.nadoc'))
    reopened = Assembly.from_json((tmp_path / '__e2e__save.nass').read_text())
    assert reopened == source
    assert verify(reopened)['status'] == 'verified'
    assert jobs.commit(identity)['status'] == 'committed'

@pytest.mark.parametrize('cursor', [-2, 0, 1])
@pytest.mark.parametrize('suppressed', [True, False])
def test_suppression_from_verified_prefix_restores_full_history_and_undo(immediate, monkeypatch, cursor, suppressed):
    from backend.api.assembly import seek_assembly_features, SeekAssemblyFeaturesRequest
    from backend.core.models import Assembly
    source = recorded()
    if not suppressed:
        jobs.commit(jobs.start(request(source))['job_id'])
    assembly_state.remember_instance_display(source.instances[0].id, representation='cylinders', visible=False)
    seek_assembly_features(SeekAssemblyFeaturesRequest(position=cursor))
    displayed = assembly_state.get_or_404().model_copy(deep=True)
    assert verify(displayed)['status'] == 'unverified'
    monkeypatch.setattr(assembly_state, 'decode_assembly_snapshot', lambda *args: pytest.fail('Recovery used as proof'))
    depth = assembly_state.undo_depth()
    identity = jobs.start(request(displayed, suppressed=suppressed))['job_id']
    result = jobs.inspect(identity)['result']
    assert result['status'] == 'ready', result
    assert result['source_assessment']['displayed_prefix_assessment']['verification_scope'] == 'displayed_prefix_reproducibility'
    assert result['source_assessment']['displayed_prefix_assessment']['assessed_cursor'] == cursor
    assert assembly_state.get_or_404() == displayed
    jobs.commit(identity)
    saved = Assembly.from_json(assembly_state.get_or_404().to_json())
    assert saved.feature_log_cursor == -1
    assert saved.feature_log[1].suppressed is suppressed
    assert saved.instances[0].name == ('Part' if suppressed else 'Renamed')
    assert saved.instances[0].representation == 'cylinders'
    assert not saved.instances[0].visible
    assert verify(saved)['status'] == 'verified'
    assert assembly_state.undo_depth() == depth + 1
    assert assembly_state.undo() == displayed
    assert assembly_state.redo() == saved


@pytest.mark.parametrize('failure', ['displayed_state', 'unseen_command', 'unseen_reference'])
def test_prefix_qualification_refuses_corrupt_display_or_unseen_tail(immediate, failure):
    from backend.api.assembly import seek_assembly_features, SeekAssemblyFeaturesRequest
    recorded()
    seek_assembly_features(SeekAssemblyFeaturesRequest(position=0))
    source = assembly_state.get_or_404()
    if failure == 'displayed_state':
        source.instances[0].name = 'Unrecorded'
    elif failure == 'unseen_command':
        source.feature_log[1].op_kind = 'unregistered-command'
    else:
        source.feature_log[1].params['instance_id'] = 'missing'
    before = source.model_copy(deep=True)
    depth, revision = assembly_state.undo_depth(), assembly_state.revision()
    identity = jobs.start(request(source))['job_id']
    result = jobs.inspect(identity)['result']
    assert result['status'] != 'ready'
    if failure == 'unseen_reference':
        assert result['issues'][0]['code'] == 'source_regeneration_failed'
    with pytest.raises(HTTPException):
        jobs.commit(identity)
    assert assembly_state.get_or_404() == before
    assert (assembly_state.undo_depth(), assembly_state.revision()) == (depth, revision)
