"""Assembly verification owns worker cleanup and rejects stale/cross-session results."""
from threading import Event
from types import SimpleNamespace
from multiprocessing.shared_memory import SharedMemory

import pytest
from fastapi import HTTPException

from backend.api import assembly_state, assembly_verification_jobs as jobs
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.core.assembly_history_contract import create_empty_assembly


@pytest.fixture
def controlled(monkeypatch):
    token = set_current_doc('assembly-job-test')
    assembly_state.load_assembly(create_empty_assembly('Part assembly'))
    entered, release, done, closed, closing, cleanup = (Event() for _ in range(6))
    cleanup.set()
    original = jobs._run

    class Worker:
        def __init__(self, source):
            pass
        def start(self):
            entered.set()
        def wait(self, timeout):
            return release.wait(timeout)
        def is_alive(self):
            return not closed.is_set()
        def result(self):
            return {'status': 'verified', 'native_editable': True, 'issues': []}
        def close(self):
            closing.set()
            assert cleanup.wait(5)
            closed.set()

    def run(*args):
        try:
            original(*args)
        finally:
            done.set()
    monkeypatch.setattr(jobs, 'AssemblyVerificationWorker', Worker)
    monkeypatch.setattr(jobs, '_run', run)
    started = jobs.start(expected_revision=assembly_state.revision())
    assert entered.wait(5)
    try:
        yield SimpleNamespace(id=started['job_id'], entered=entered, release=release,
                              done=done, closed=closed, closing=closing, cleanup=cleanup)
    finally:
        cleanup.set()
        release.set()
        assert done.wait(5)
        with jobs._lock:
            jobs._jobs.pop(started['job_id'], None)
        assembly_state.close_session()
        reset_current_doc(token)


def test_cancel_reaps_worker_and_cannot_return_verified(controlled):
    jobs.inspect(controlled.id, cancel=True)
    assert controlled.done.wait(5)
    assert controlled.closed.is_set()
    result = jobs.inspect(controlled.id)['result']
    assert result['status'] == 'unverified'
    assert result['issues'][0]['code'] == 'cancelled'


def test_admission_is_held_until_cleanup_finishes(controlled):
    controlled.cleanup.clear()
    jobs.inspect(controlled.id, cancel=True)
    assert controlled.closing.wait(5)
    with pytest.raises(HTTPException) as error:
        jobs.start()
    assert error.value.status_code == 429
    from backend.api.part_verification_jobs import start as start_part
    with pytest.raises(HTTPException) as error:
        start_part()
    assert error.value.status_code == 429


def test_revision_change_stops_running_worker(controlled):
    source = assembly_state.get_or_404()
    assembly_state.set_assembly(source.model_copy(update={'metadata': source.metadata.model_copy(update={'name': 'Changed'})}))
    assert controlled.done.wait(5)
    result = jobs.inspect(controlled.id)
    assert result['stale']
    assert result['result']['status'] == 'unverified'


def test_same_revision_reopened_session_does_not_reuse_old_result(controlled):
    source = assembly_state.get_or_404()
    assembly_state.close_session()
    assembly_state.load_assembly(source)
    assert controlled.done.wait(5)
    assert jobs.inspect(controlled.id)['stale']


def test_document_scope_and_post_completion_cancellation(controlled):
    token = set_current_doc('other-assembly')
    try:
        with pytest.raises(HTTPException) as error:
            jobs.inspect(controlled.id, cancel=True)
        assert error.value.status_code == 404
    finally:
        reset_current_doc(token)
    controlled.release.set()
    assert controlled.done.wait(5)
    result = jobs.inspect(controlled.id)
    assert result['result']['status'] == 'verified'
    assert result['result']['assembly_id'] == assembly_state.get_or_404().id
    assert jobs.inspect(controlled.id, cancel=True)['result']['status'] == 'unverified'


def test_http_routes_use_document_scope_and_strict_revision(controlled):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    client = TestClient(app)
    headers = {'X-NADOC-Doc': 'assembly-job-test'}
    path = f'/api/assembly/features/verification/jobs/{controlled.id}'
    assert client.get(path, headers=headers).status_code == 200
    assert client.get(path, headers={'X-NADOC-Doc': 'other'}).status_code == 404
    assert client.post('/api/assembly/features/verification/jobs', headers=headers, json={'expected_revision': True}).status_code == 422
    assert client.delete(path, headers=headers).status_code == 200
    assert controlled.done.wait(5)


def test_actual_spawned_worker_reports_and_releases_shared_memory():
    from backend.api.assembly_verification_worker import AssemblyVerificationWorker
    worker = AssemblyVerificationWorker(create_empty_assembly('Spawned'))
    names = [buffer.name for buffer in worker._buffers]
    try:
        worker.start()
        assert worker.wait(20)
        result = worker.result()
        assert result['status'] == 'verified', result
    finally:
        worker.close()
    for name in names:
        with pytest.raises(FileNotFoundError):
            SharedMemory(name=name)


def test_capture_omits_outer_recovery_and_isolates_mutable_inputs():
    from backend.core.assembly_verification_capture import capture
    from backend.core.part_capture_graph import CaptureLimit
    from tests.test_assembly_history_verification import recorded
    from backend.api import state
    try:
        source = recorded()
        source.feature_log[0].post_state_gz_b64 = 'x' * 20_000_000
        captured = capture(source)
        assert captured.feature_log[0].post_state_gz_b64 == ''
        captured.instances[0].source.design.metadata.name = 'private'
        assert source.instances[0].source.design.metadata.name != 'private'
        with pytest.raises(CaptureLimit):
            capture(source, max_nodes=1)
    finally:
        assembly_state.close_session()
        state.close_session()


def test_failed_capture_or_revision_admission_releases_slot(monkeypatch):
    from backend.core.part_capture_graph import CaptureLimit
    from backend.api.part_history_verification import _slot
    assembly_state.load_assembly(create_empty_assembly())
    try:
        with pytest.raises(HTTPException) as error:
            jobs.start(expected_revision=-1)
        assert error.value.status_code == 409
        assert _slot.acquire(blocking=False)
        _slot.release()
        def fail():
            raise CaptureLimit('test capture limit')
        monkeypatch.setattr(assembly_state, 'capture_for_verification', fail)
        with pytest.raises(HTTPException) as error:
            jobs.start()
        assert error.value.status_code == 413
        assert _slot.acquire(blocking=False)
        _slot.release()
    finally:
        assembly_state.close_session()


def test_completed_result_expires(controlled, monkeypatch):
    controlled.release.set()
    assert controlled.done.wait(5)
    monkeypatch.setattr(jobs, 'RESULT_TTL', -1)
    with pytest.raises(HTTPException) as error:
        jobs.inspect(controlled.id)
    assert error.value.status_code == 404
