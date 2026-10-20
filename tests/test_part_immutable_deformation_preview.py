"""Sealed history uses the shared preview lease, true prefix and native display."""
from multiprocessing.shared_memory import SharedMemory
from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import state, part_publication_policy as policy
from backend.api import part_deformation_preview_sessions as host
from backend.api import part_immutable_deformation_preview as adapter
from backend.api import part_immutable_revision as revisions
from backend.api import part_preview_family_work as family
from backend.core.part_verification_capture import capture
from tests.test_part_immutable_geometry_host import document as document, saved, available
from tests.test_part_deformation_preview import native_source, patch, _append
from tests.test_part_deformation_preview_sessions import Timer, update, cancellation
from backend.core.models import SnapshotLogEntry
from backend.api.crud import BundleRequest


@pytest.fixture(autouse=True)
def cleanup(monkeypatch):
    monkeypatch.setattr(host, 'Timer', Timer)
    yield
    host.clear_for_testing()


def install(document, kind):
    _, session = document
    source = native_source(kind)
    source = _append(source, SnapshotLogEntry(id='suffix', op_kind='bundle-create', label='Tail',
        params={**BundleRequest(cells=[[6, 6]], length_bp=7, name='Tail', history_seed=uuid4()).model_dump(mode='json'), '_proof_version': 1}))
    session.design = revisions.prepare_geometry_revision(source)
    session.revision = 7
    session.redo.append(session.design)
    origin = {'preview_id': str(uuid4()), 'expected_design_id': source.id,
              'expected_revision': 7, 'feature_id': 'edited-feature'}
    return source, origin


@pytest.mark.parametrize('kind', ['bend', 'twist'])
def test_real_sealed_prepare_evaluate_cancel_matches_prefix_with_suffix(document, monkeypatch, kind):
    source, origin = install(document, kind)
    expected = family.prepare('deformation', capture(source, preserve_entry_types=True), origin['feature_id'])
    original = family.evaluate_original('deformation', expected)
    before = saved(document[1])
    children = []
    worker = adapter.PreviewWorker
    def observed(*args):
        child = worker(*args)
        children.append((child, child._input.name, child._output.name))
        return child
    monkeypatch.setattr(adapter, 'PreviewWorker', observed)
    monkeypatch.setattr(adapter, '_decoded_exact', lambda *a: pytest.fail('Parent decoded'))
    monkeypatch.setattr(host, 'capture', lambda *a, **k: pytest.fail('Parent captured'))
    opened = host.prepare(origin)
    envelope = {k: opened[k] for k in ('preview_id', 'expected_design_id', 'expected_revision',
        'feature_id', 'lease_id', 'doc_id', 'deformation_id', 'request_sequence', 'remaining_seconds')}
    assert opened == family.prepare_display('deformation', expected, original, envelope=envelope)
    assert {h['id'] for h in opened['control_context']['helices']} == {'h_XY_0_0', 'h_XY_0_1'}
    assert {h.id for h in source.helices} == {'h_XY_6_6'}
    assert type(host._entries[document[0]].prepared) is adapter.Prepared
    request = update(opened, params=patch(kind))
    changed = host.evaluate(request)
    envelope.update(request_sequence=1, remaining_seconds=changed['remaining_seconds'])
    assert changed == family.evaluate_display('deformation', expected, family.evaluate('deformation', expected, patch(kind)),
        include_geometry=True, envelope=envelope)
    assert host.cancel(cancellation(opened))['status'] == 'cancelled'
    assert saved(document[1]) == before and document[0] not in host._entries
    assert len(children) == 2
    for child, *names in children:
        assert child._closed and child._process_closed
        for name in names:
            with pytest.raises(FileNotFoundError): SharedMemory(name=name)
    available()


@pytest.mark.parametrize('change', ['revision', 'source', 'session', 'policy', 'gate', 'cancel', 'expiry', 'sequence'])
@pytest.mark.parametrize('phase', ['prepare', 'evaluate'])
def test_inflight_work_cannot_return_late_packet(document, monkeypatch, change, phase):
    source, origin = install(document, 'bend')
    doc, session = document
    opened = host.prepare(origin) if phase == 'evaluate' else None
    worker = adapter.PreviewWorker
    children = []
    class Changed(worker):
        def start(self):
            super().start()
            if change == 'revision': session.revision += 1
            elif change == 'source': session.design = revisions.prepare_geometry_revision(source)
            elif change == 'session': state.drop_doc(doc)
            elif change == 'policy': policy._install_configuration(policy.current_configuration())
            elif change == 'gate': monkeypatch.setattr(adapter.authority, 'ENABLED', False)
            elif change == 'cancel': host.cancel(origin)
            elif change == 'expiry': host._entries[doc].expires = 0; host._expire(host._entries[doc])
            else: host._entries[doc].sequence += 1
    def observed(*args):
        child = Changed(*args);children.append((child, child._input.name, child._output.name));return child
    monkeypatch.setattr(adapter, 'PreviewWorker', observed)
    with pytest.raises(HTTPException):
        if phase == 'prepare': host.prepare(origin)
        else: host.evaluate(update(opened))
    if phase == 'prepare' or change in {'cancel', 'expiry'}:
        assert doc not in host._entries
    assert not session.history
    assert len(children) == 1
    for child, *names in children:
        assert child._closed and child._process_closed
        for name in names:
            with pytest.raises(FileNotFoundError): SharedMemory(name=name)
    available()



def test_sealed_creation_and_other_families_refuse_without_lease(document):
    _, origin = install(document, 'bend')
    before = saved(document[1])
    with pytest.raises(HTTPException):
        host.prepare_create({**origin, 'feature_id': str(uuid4()), 'mode': 'create',
            'type': 'bend', 'targets': None, 'cluster_ids': []})
    for kind in ('sweep', 'transform'):
        with pytest.raises(HTTPException): host.prepare(origin, family=kind)
    assert document[0] not in host._entries and saved(document[1]) == before
    available()


def test_sealed_expired_nonce_and_disabled_gate_refuse_without_spawn(document, monkeypatch):
    _, origin = install(document, 'bend')
    host.cancel(origin)
    monkeypatch.setattr(adapter, 'PreviewWorker', lambda *a: pytest.fail('Refused request spawned'))
    with pytest.raises(HTTPException): host.prepare(origin)
    monkeypatch.setattr(adapter.authority, 'ENABLED', False)
    with pytest.raises(HTTPException): host.prepare({**origin, 'preview_id': str(uuid4())})
    assert document[0] not in host._entries
    available()



def test_feedback_only_evaluation_keeps_prefix_identity_and_no_geometry(document):
    _, origin = install(document, 'twist')
    before = saved(document[1])
    opened = host.prepare(origin)
    response = host.evaluate({**update(opened, params=patch('twist')), 'include_geometry': False})
    assert response['candidate'] is None and response['feasibility'] is not None
    assert response['deformation_id'] == opened['deformation_id']
    assert response['stage'] == 'feature' and response['downstream_evaluated'] is False
    assert saved(document[1]) == before
    host.cancel(cancellation(opened))
    available()
