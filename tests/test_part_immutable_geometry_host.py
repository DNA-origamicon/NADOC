"""Source-bound immutable extrusion publication and exact-handle undo/redo."""

from threading import Event
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import doc_context, state, part_publication_policy as policy
from backend.api import part_immutable_geometry_host as host
from backend.api import part_immutable_geometry_publication as authority
from backend.api import part_immutable_geometry_worker as transport
from backend.api import part_immutable_revision as revisions
from backend.api.part_history_verification import _slot
from tests.test_part_immutable_geometry_worker import prepared, KINDS
from tests.test_group_organization_history import _verified


@pytest.fixture
def document(monkeypatch):
    doc = f'__immutable_geometry__{uuid4()}'
    token = doc_context.set_current_doc(doc)
    markers = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    monkeypatch.setattr(policy, '_configuration', (policy.HostPolicyConfiguration(
        document_modes={doc: 'registered_only'}), 7))
    monkeypatch.setattr(authority, 'ENABLED', True)
    with state._lock:
        session = state._session()
    try:
        yield doc, session
    finally:
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(markers[0])
        doc_context.set_request_feature_log_entry_id(markers[1])


def install(document, kind='bundle-create'):
    _, session = document
    source, _, operation = prepared(kind)
    source.annotations_enabled = False
    session.design = revisions.prepare_geometry_revision(source)
    session.revision = 7
    return session.design, operation


def edit(operation, **kwargs):
    header, request = operation['header'], operation['request']
    return host.edit(request['index'], request['params'], expected_kind=header['expected_kind'],
        expected_feature_id=header['expected_feature_id'], expected_design_id=header['source_design_id'],
        expected_revision=request['expected_revision'], **kwargs)


def saved(session):
    return session.design, session.revision, list(session.history), list(session.redo)


def available():
    assert _slot.acquire(blocking=False)
    _slot.release()


@pytest.fixture
def immediate(monkeypatch):
    controls = SimpleNamespace(start=None, result=None, closed=0)

    class Worker:
        def __init__(self, ticket, operation):
            assert state._lock.acquire(blocking=False)
            state._lock.release()
            self.parts, _ = transport.encode_input(ticket, operation)

        def start(self):
            if controls.start:
                controls.start()

        def wait(self, timeout):
            return True

        def is_alive(self):
            return False

        def result(self):
            result = transport.evaluate_payload(b''.join(self.parts))['result']
            return controls.result(result) if controls.result else result

        def close(self):
            controls.closed += 1

    monkeypatch.setattr(transport, 'GeometryEvaluationWorker', Worker)
    return controls


@pytest.mark.parametrize('kind', KINDS)
def test_native_edit_one_publication_exact_undo_redo_and_reload(document, immediate, monkeypatch, kind):
    _, session = document
    source, operation = install(document, kind)
    original_prepare = host.prepare_geometry_revision

    def prepare(candidate, **kwargs):
        assert state._lock.acquire(blocking=False)
        state._lock.release()
        return original_prepare(candidate, **kwargs)

    monkeypatch.setattr(host, 'prepare_geometry_revision', prepare)
    monkeypatch.setattr(state, '_snapshot_copy', lambda *_: pytest.fail('Immutable history deep-copied a model'))
    result = edit(operation)
    candidate = session.design
    assert result['revision'] == session.revision == 8
    assert list(session.history) == [source] and not session.redo
    model = revisions.materialize_revision(candidate)
    _verified(model)
    assert model.annotations_enabled is False
    identity = result['design_id']
    host.history('undo', expected_design_id=identity, expected_revision=8)
    assert session.design is source and not session.history and list(session.redo) == [candidate]
    host.history('redo', expected_design_id=identity, expected_revision=9)
    assert session.design is candidate and list(session.history) == [source] and not session.redo
    assert session.revision == 10 and immediate.closed == 1
    available()


def test_real_worker_publishes_then_replays_independently(document):
    _, session = document
    source, operation = install(document)
    result = edit(operation)
    assert result['revision'] == 8 and session.history[-1] is source
    _verified(revisions.materialize_revision(session.design))
    available()


@pytest.mark.parametrize('change', ['revision', 'source', 'session', 'policy', 'gate', 'cancel'])
def test_worker_phase_context_change_cannot_publish(document, immediate, change):
    doc, session = document
    source, operation = install(document)
    cancelled = Event()

    def changed():
        if change == 'revision': session.revision += 1
        elif change == 'source': session.design = revisions.prepare_geometry_revision(revisions.materialize_revision(source))
        elif change == 'session': state.drop_doc(doc)
        elif change == 'policy': policy._install_configuration(policy.current_configuration())
        elif change == 'gate': authority.ENABLED = False
        else: cancelled.set()

    immediate.start = changed
    with pytest.raises(HTTPException):
        edit(operation, cancelled=cancelled)
    assert not session.history and not session.redo
    assert session.design is source or change == 'source'
    assert immediate.closed == 1
    available()


@pytest.mark.parametrize('change', ['revision', 'source', 'session', 'policy', 'gate', 'cancel', 'deadline'])
def test_candidate_preparation_context_change_cannot_publish(document, immediate, monkeypatch, change):
    doc, session = document
    source, operation = install(document)
    cancelled = Event()
    original = host.prepare_geometry_revision

    def prepare(candidate, **kwargs):
        result = original(candidate, **kwargs)
        if change == 'revision': session.revision += 1
        elif change == 'source': session.design = original(revisions.materialize_revision(source))
        elif change == 'session': state.drop_doc(doc)
        elif change == 'policy': policy._install_configuration(policy.current_configuration())
        elif change == 'gate': monkeypatch.setattr(authority, 'ENABLED', False)
        elif change == 'cancel': cancelled.set()
        else: monkeypatch.setattr(host, 'monotonic', lambda: float('inf'))
        return result

    monkeypatch.setattr(host, 'prepare_geometry_revision', prepare)
    with pytest.raises(HTTPException):
        edit(operation, cancelled=cancelled)
    assert not session.history and not session.redo
    assert session.design is source or change == 'source'
    available()


@pytest.mark.parametrize('action', ['edit', 'undo', 'redo'])
def test_revision_assignment_failure_rolls_back_everything(document, immediate, monkeypatch, action):
    _, session = document
    _, operation = install(document)
    if action != 'edit':
        edit(operation)
    if action == 'redo':
        host.history('undo', expected_design_id=operation['header']['source_design_id'], expected_revision=8)
    before = saved(session)
    original = state._bump_revision

    def fail(current):
        original(current)
        raise RuntimeError('injected revision failure')

    monkeypatch.setattr(state, '_bump_revision', fail)
    with pytest.raises(RuntimeError, match='injected'):
        if action == 'edit': edit(operation)
        else: host.history(action, expected_design_id=operation['header']['source_design_id'], expected_revision=session.revision)
    assert saved(session) == before
    available()


def test_gate_and_stale_history_refuse_without_copy_or_mutation(document, immediate, monkeypatch):
    _, session = document
    _, operation = install(document)
    edit(operation)
    before = saved(session)
    with pytest.raises(HTTPException):
        host.history('undo', expected_design_id=operation['header']['source_design_id'], expected_revision=7)
    monkeypatch.setattr(authority, 'ENABLED', False)
    with pytest.raises(HTTPException):
        host.history('undo', expected_design_id=operation['header']['source_design_id'], expected_revision=8)
    assert saved(session) == before


def test_invalid_candidate_schema_never_publishes(document, immediate):
    _, session = document
    _, operation = install(document)
    before = saved(session)
    def corrupt(result):
        result['candidate']['helices'][0]['length_bp'] = 'invalid'
        return result
    # The transport is a trusted native-worker boundary, not a hostile-code
    # sandbox. Exercise structural corruption rather than claiming proof against
    # an attacker who can replace the trusted worker implementation.
    immediate.result = corrupt
    with pytest.raises(HTTPException):
        edit(operation)
    assert saved(session) == before
    available()


def test_successful_permit_is_consumed_and_cannot_be_replayed(document, immediate, monkeypatch):
    from backend.api import part_publication_permit as permits
    doc, session = document
    _, operation = install(document)
    issued = []
    original = authority.issue

    def issue(*args, **kwargs):
        permit = original(*args, **kwargs)
        issued.append(permit)
        return permit

    monkeypatch.setattr(authority, 'issue', issue)
    edit(operation)
    with pytest.raises(HTTPException) as error:
        permits.check_publication(issued[0], doc_id=doc, session=session, candidate=session.design)
    assert 'already consumed' in error.value.detail['detail']


@pytest.mark.parametrize('fault', ['request', 'authoring', 'recipe', 'cancel', 'candidate'])
def test_permit_binding_rejects_substitution(document, immediate, monkeypatch, fault):
    _, session = document
    source, operation = install(document)
    before = saved(session)
    original = authority.issue

    def issue(admission, candidate, **kwargs):
        if fault in {'request', 'authoring', 'recipe'}:
            kwargs[f'{fault}_sha256'] = '0' * 64
        elif fault == 'cancel':
            kwargs['cancelled'].set()
        else:
            candidate = source
        return original(admission, candidate, **kwargs)

    monkeypatch.setattr(authority, 'issue', issue)
    with pytest.raises(HTTPException):
        edit(operation)
    assert saved(session) == before
    available()


def test_retention_refusal_leaves_source_and_history_unchanged(document, immediate, monkeypatch):
    from backend.api import part_immutable_storage as storage
    _, session = document
    _, operation = install(document)
    before = saved(session)
    monkeypatch.setattr(storage, 'MAX_RETAINED_REVISION_BYTES', 1)
    with pytest.raises(HTTPException) as error:
        edit(operation)
    assert error.value.status_code == 413
    assert saved(session) == before
    available()


def test_edit_after_undo_discards_redo_and_caller_mutation_cannot_change_edit(document, immediate):
    _, session = document
    source, operation = install(document)
    edit(operation)
    host.history('undo', expected_design_id=operation['header']['source_design_id'], expected_revision=8)
    operation['request']['expected_revision'] = 9
    operation['header']['source_revision'] = 9
    operation['request']['params']['length_bp'] = 28
    immediate.start = lambda: operation['request']['params'].update(length_bp=999)
    edit(operation)
    assert list(session.history) == [source] and not session.redo
    assert revisions.materialize_revision(session.design).feature_log[0].params['length_bp'] == 28
    available()


@pytest.mark.parametrize('fault', ['cancel', 'gate', 'policy'])
def test_liveness_is_rechecked_after_undo_retention_preparation(document, immediate, monkeypatch, fault):
    from backend.api import part_immutable_storage as storage
    _, session = document
    _, operation = install(document)
    before = saved(session)
    cancelled = Event()
    original = storage.retained_history

    def retention(*args, **kwargs):
        result = original(*args, **kwargs)
        if fault == 'cancel': cancelled.set()
        elif fault == 'gate': monkeypatch.setattr(authority, 'ENABLED', False)
        else: policy._install_configuration(policy.current_configuration())
        return result

    monkeypatch.setattr(storage, 'retained_history', retention)
    with pytest.raises(HTTPException):
        edit(operation, cancelled=cancelled)
    assert saved(session) == before
    available()


@pytest.mark.parametrize('kind', ['bend', 'twist'])
def test_real_native_stage_is_private_and_retains_only_sealed_candidate(document, monkeypatch, kind):
    from dataclasses import fields
    from backend.core.models import Design
    from tests.test_part_deformation_preview import native_source

    _, session = document
    source = native_source(kind)
    entry = source.feature_log[-1]
    session.design = revisions.prepare_geometry_revision(source)
    session.revision = 7
    session.redo.append(session.design)
    before = saved(session)
    monkeypatch.setattr(authority, 'issue', lambda *a, **k: pytest.fail('Staging issued a permit'))
    staged = host._stage('edit', len(source.feature_log) - 1, {'plane_b_bp': 30},
        expected_kind='deformation', expected_feature_id=entry.id,
        expected_design_id=source.id, expected_revision=7)
    assert saved(session) == before
    assert staged.session() is session and staged.context.source() is before[0]
    assert staged.context.source_revision == 7
    assert staged.context.request_sha256 == staged.request_hash
    assert not any(isinstance(getattr(staged, field.name), Design) for field in fields(staged))
    assert type(staged.prepared) is revisions.StrictPartRevision
    candidate = revisions.materialize_revision(staged.prepared)
    assert candidate.deformations[-1].plane_b_bp == 30
    assert candidate.feature_log[-1].id == entry.id
    _verified(candidate)
    available()


@pytest.mark.parametrize('change', ['revision', 'source', 'session', 'policy', 'gate', 'cancel', 'deadline'])
def test_staging_publication_gap_rechecks_original_authority(document, immediate, monkeypatch, change):
    doc, session = document
    source, operation = install(document)
    original = host._stage

    def stage(*args, **kwargs):
        result = original(*args, **kwargs)
        if change == 'revision': session.revision += 1
        elif change == 'source': session.design = revisions.prepare_geometry_revision(revisions.materialize_revision(source))
        elif change == 'session': state.drop_doc(doc)
        elif change == 'policy': policy._install_configuration(policy.current_configuration())
        elif change == 'gate': monkeypatch.setattr(authority, 'ENABLED', False)
        elif change == 'cancel': result.cancelled.set()
        else: monkeypatch.setattr(host, 'monotonic', lambda: float('inf'))
        return result

    monkeypatch.setattr(host, '_stage', stage)
    monkeypatch.setattr(authority, 'issue', lambda *a, **k: pytest.fail('Stale staging issued permit'))
    with pytest.raises(HTTPException):
        edit(operation)
    assert not session.history and not session.redo
    assert session.design is source or change == 'source'
    available()
