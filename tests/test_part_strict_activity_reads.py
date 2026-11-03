"""Real strict activity dispatch; isolated jobs/fake processes, no effects."""
import asyncio
import json
from threading import Event
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient
import pytest

from backend.api import assembly, part_publication_policy as policy, state
from backend.api import part_strict_activity_reads as reads
from backend.api.part_strict_http import StrictPartDispatch
from backend.core.activity_evidence_io import Evidence
from tests.test_part_strict_http import documents as documents, forbidden_app

URL = '/api/jobs/active'


@pytest.fixture
def isolated(documents, tmp_path, monkeypatch):
    proc = tmp_path / 'proc'; proc.mkdir()
    monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path)
    monkeypatch.setattr(reads, 'Evidence', lambda **kwargs: Evidence(proc, **kwargs))
    from backend.api import routes_jobs
    from backend.core import job_archive, mrdna_runner
    for module, name in [(routes_jobs, '_collect_active'), (job_archive, 'cache_job_metadata'),
                         (mrdna_runner, 'reconcile_mrdna_status'), (mrdna_runner, '_load_snapshot_design')]:
        monkeypatch.setattr(module, name, lambda *a, **k: pytest.fail('Legacy/effect path entered'))
    with TestClient(StrictPartDispatch(forbidden_app), headers={'X-NADOC-Doc': documents[0]}) as client:
        yield client


def job(root, status='running', *, source='fixture.nadoc'):
    directory = root / 'mrdna_jobs/job'; directory.mkdir(parents=True)
    (directory / 'job.json').write_text(json.dumps(dict(job_id='job', design_name='Fixture',
        status=status, created_at=1, design_source_path=source)))
    return directory


def files(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}


@pytest.mark.parametrize('mode', ['empty', 'terminal', 'cached', 'live'])
def test_real_dispatch_complete_catalog_preserves_shape(isolated, documents, tmp_path, mode):
    if mode != 'empty':
        directory = job(tmp_path, 'completed' if mode == 'terminal' else 'running')
        if mode == 'cached': (directory / 'display.json').write_text('{}')
        if mode == 'live':
            process = tmp_path / 'proc/321'; process.mkdir()
            (process / 'cmdline').write_bytes(b'arbd\0relative.conf')
            (process / 'cwd').symlink_to(directory)
    before = files(tmp_path)
    result = isolated.get(URL)
    assert result.status_code == 200, result.text
    expected = [] if mode != 'live' else [dict(engine='mrdna', job_id='job', design_name='Fixture',
        design_source_path='fixture.nadoc', status='running', created_at=1, execution_target='local',
        resource_class='gpu', eta_seconds=None)]
    assert result.json() == {'jobs': expected, 'count': len(expected), 'any_running': bool(expected)}
    assert files(tmp_path) == before and documents[0] not in state._sessions
    assert not list(tmp_path.rglob('.runtime.lock'))


@pytest.mark.parametrize('mode', ['preparing', 'missing-source', 'malformed', 'archive', 'budget'])
def test_incomplete_catalog_never_becomes_empty_success(isolated, tmp_path, mode):
    directory = job(tmp_path, 'preparing' if mode == 'preparing' else 'running')
    if mode == 'missing-source':
        process = tmp_path / 'proc/321'; process.mkdir()
        (process / 'cmdline').write_bytes(b'arbd\0' + str(directory).encode())
        (process / 'cwd').symlink_to(directory)
        payload = json.loads((directory / 'job.json').read_text());payload['design_source_path'] = None
        (directory / 'job.json').write_text(json.dumps(payload))
    if mode == 'malformed': (directory / 'job.json').write_text('bad json')
    if mode == 'archive': (directory.parent / '.archive_index.json').write_text('{"job":"/unavailable"}')
    if mode == 'budget': (directory / 'job.json').write_text('x' * 16385)
    before = files(tmp_path); result = isolated.get(URL)
    assert result.status_code == (413 if mode == 'budget' else 409), result.text
    assert result.json()['detail']['code'] == ('activity_evidence_limit' if mode == 'budget' else 'activity_evidence_incomplete')
    assert 'jobs' not in result.json() and files(tmp_path) == before


@pytest.mark.parametrize('query', ['workspace=/tmp', 'verified=true', 'doc=duplicate'])
def test_query_refuses_before_work(isolated, monkeypatch, query):
    monkeypatch.setattr(reads, 'activity_catalog', lambda *a, **k: pytest.fail('Query entered work'))
    if query == 'doc=duplicate':
        doc = isolated.headers['X-NADOC-Doc']; query = f'doc={doc}&doc={doc}'
    assert isolated.get(URL + '?' + query).status_code == 422


def test_method_and_body_never_fall_through(isolated):
    for method in ('post', 'put', 'delete', 'patch'):
        assert getattr(isolated, method)(URL).status_code == 403
    assert isolated.request('GET', URL, content=b'x').status_code == 413
    assert isolated.get(URL, headers={'Content-Type': 'application/json'}).status_code == 415


@pytest.mark.parametrize('change', ['policy', 'session', 'workspace', 'removed'])
def test_identity_change_during_work_refuses(isolated, documents, tmp_path, monkeypatch, change):
    original = reads.activity_catalog
    def changed(workspace, **kwargs):
        result = original(workspace, **kwargs)
        if change == 'policy':
            state.configure_part_publication_policy(policy.HostPolicyConfiguration(document_modes={documents[0]: 'registered_only'}))
        elif change == 'session':
            with state._lock: state._sessions[documents[0]] = SimpleNamespace(identity='replacement')
        elif change == 'workspace': monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path / 'other')
        else: (tmp_path / 'proc').rmdir(); tmp_path.rmdir()
        return result
    monkeypatch.setattr(reads, 'activity_catalog', changed)
    result = isolated.get(URL)
    assert result.status_code == (503 if change == 'removed' else 409), result.text
    if change == 'session':
        with state._lock: state._sessions.pop(documents[0], None)


def test_unavailable_workspace_does_not_claim_empty(isolated, tmp_path, monkeypatch):
    monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path / 'missing')
    result = isolated.get(URL)
    assert result.status_code == 503 and result.json()['detail']['code'] == 'activity_workspace_unavailable'


def test_shared_slot_refuses_without_starting_work(isolated, monkeypatch):
    monkeypatch.setattr(reads, 'activity_catalog', lambda *a, **k: pytest.fail('Busy slot entered work'))
    assert reads._slot.acquire(blocking=False)
    try: assert isolated.get(URL).status_code == 429
    finally: reads._slot.release()


def test_deadline_refuses_even_if_catalog_returns_ready(isolated, monkeypatch):
    monkeypatch.setattr(reads, 'MAX_SECONDS', -1)
    result = isolated.get(URL)
    assert result.status_code == 408 and result.json()['detail']['code'] == 'activity_time_limit'


def test_wire_budget_checked_before_success(isolated, monkeypatch):
    monkeypatch.setattr(reads, 'activity_catalog', lambda *a, **k: {'complete': True, 'records': [
        {'active': True, 'issues': [], 'summary': {'status': 'running', 'design_name': 'x' * 2_000_001}}]})
    assert isolated.get(URL).status_code == 413


def test_cancellation_retains_slot_until_thread_stops(documents, tmp_path, monkeypatch):
    monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path)
    entered, release, stopped = Event(), Event(), Event()
    def blocked(*args):
        entered.set()
        try: assert release.wait(3)
        finally: stopped.set()
    monkeypatch.setattr(reads, '_read', blocked)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=StrictPartDispatch(forbidden_app)),
                base_url='http://test', headers={'X-NADOC-Doc': documents[0]}) as client:
            task = asyncio.create_task(client.get(URL))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                task.cancel()
                await asyncio.sleep(.02)
                task.cancel()
                await asyncio.sleep(.02)
                assert not stopped.is_set()
                assert (await client.get(URL)).status_code == 429
            finally:
                release.set()
                with pytest.raises(asyncio.CancelledError): await task
            assert stopped.is_set()
            assert reads._slot.acquire(blocking=False)
            reads._slot.release()
    asyncio.run(exercise())


@pytest.mark.parametrize('change', ['policy', 'workspace'])
def test_identity_rechecked_after_response_encoding(isolated, documents, tmp_path, monkeypatch, change):
    original = reads.response
    def changed(*args):
        result = original(*args)
        if change == 'policy':
            state.configure_part_publication_policy(policy.HostPolicyConfiguration(document_modes={documents[0]: 'registered_only'}))
        else: monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path / 'other')
        return result
    monkeypatch.setattr(reads, 'response', changed)
    assert isolated.get(URL).status_code == 409


def test_work_budget_is_structured_limit(isolated, tmp_path, monkeypatch):
    def exhausted(**kwargs):
        evidence = Evidence(tmp_path / 'proc', **kwargs); evidence.work = 0
        return evidence
    monkeypatch.setattr(reads, 'Evidence', exhausted)
    result = isolated.get(URL)
    assert result.status_code == 413 and result.json()['detail']['code'] == 'activity_evidence_limit'


def test_evidence_observes_request_cancellation():
    from backend.core.activity_evidence_io import EvidenceUnavailable
    cancelled = Event(); evidence = Evidence(cancelled=cancelled); cancelled.set()
    with pytest.raises(EvidenceUnavailable, match='cancelled'): evidence.tick()
