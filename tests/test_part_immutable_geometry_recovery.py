"""Real typed files, explicit geometry recovery and the existing lease owner."""

from fastapi import HTTPException
import pytest

from backend.api import part_evaluation_jobs as jobs, state
from backend.api import part_immutable_recovery as recovery
from backend.api import part_immutable_recovery_worker as transport
from backend.api import part_immutable_geometry_publication as authority
from backend.api import part_immutable_geometry_host as geometry
from backend.api.part_immutable_persistence import capture_immutable
from backend.api.part_immutable_revision import materialize_revision, revision_metadata
from tests.test_part_immutable_recovery import document as document, immediate as immediate
from tests.test_part_immutable_geometry_worker import prepared, KINDS
from tests.test_group_organization_history import _verified


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(authority, 'ENABLED', True)


def store(document, kind='bundle-create'):
    doc, owner = document
    _, source, operation = prepared(kind)
    owner.cache.write(owner.reserve_empty(doc), source)
    return source, operation


def start():
    response = recovery.start_geometry({'expected_revision': 0})
    identity = response['job_id']
    return identity, jobs._jobs[identity]


@pytest.mark.parametrize('kind', KINDS)
def test_every_extrusion_family_recovers_exact_file_without_batch_authority(immediate, kind):
    doc, owner = immediate
    original, _ = store(immediate, kind)
    identity, job = start()
    assert job.result['status'] == 'ready', job.result
    assert job.candidate.payload == original.payload
    assert revision_metadata(job.candidate).scope_tag == 'native_extrusion_v1'
    result = jobs.commit(identity)
    session = state._sessions[doc]
    assert result['revision'] == 1 and not session.history and not session.redo
    assert session.design.payload == owner.read_pending(doc).payload == original.payload
    _verified(materialize_revision(session.design))


def test_real_recover_edit_persist_close_recover_cycle(document):
    doc, owner = document
    original, operation = store(document)
    identity, job = start()
    assert job.result['status'] == 'ready', job.result
    jobs.commit(identity)
    header, request = operation['header'], operation['request']
    result = geometry.edit(request['index'], request['params'], expected_kind=header['expected_kind'],
        expected_feature_id=header['expected_feature_id'], expected_design_id=header['source_design_id'],
        expected_revision=1)
    published = state._sessions[doc].design
    assert result['revision'] == 2 and published.payload != original.payload
    capture = capture_immutable(doc)
    assert owner.write_capture(capture) == 2
    assert owner.read_pending(doc).payload == published.payload
    geometry.history('undo', expected_design_id=header['source_design_id'], expected_revision=2)
    assert owner.write_capture(capture_immutable(doc)) == 3
    assert owner.write_capture(capture) == 3  # An older save cannot overwrite undo.
    assert owner.read_pending(doc).payload == original.payload
    geometry.history('redo', expected_design_id=header['source_design_id'], expected_revision=3)
    assert owner.write_capture(capture_immutable(doc)) == 4
    assert owner.read_pending(doc).payload == published.payload
    state.drop_doc(doc)
    identity, job = start()
    assert job.result['status'] == 'ready', job.result
    jobs.commit(identity)
    restored = state._sessions[doc].design
    assert restored.payload == published.payload and restored is not published
    _verified(materialize_revision(restored))


def test_existing_restore_cannot_infer_or_promote_geometry_scope(immediate):
    doc, owner = immediate
    original, _ = store(immediate)
    identity = recovery.start({'expected_revision': 0})['job_id']
    assert jobs.inspect(identity)['result']['status'] != 'ready'
    with pytest.raises(HTTPException):
        jobs.commit(identity)
    assert state._sessions[doc].design is None
    assert owner.read_pending(doc).payload == original.payload


@pytest.mark.parametrize('phase', ['admission', 'commit'])
def test_geometry_gate_refuses_without_publishing_or_rewriting_file(immediate, monkeypatch, phase):
    doc, owner = immediate
    original, _ = store(immediate)
    if phase == 'commit':
        identity, job = start()
        assert job.result['status'] == 'ready'
    monkeypatch.setattr(authority, 'ENABLED', False)
    with pytest.raises(HTTPException):
        start() if phase == 'admission' else jobs.commit(identity)
    assert state._sessions.get(doc) is None or state._sessions[doc].design is None
    assert owner.read_pending(doc).payload == original.payload


def test_replaced_file_lease_blocks_previously_qualified_candidate(immediate):
    doc, owner = immediate
    original, _ = store(immediate)
    identity, job = start()
    assert job.result['status'] == 'ready'
    # Same bytes, new inode/lease: an earlier observation cannot authorize it.
    owner.cache.write(owner.read_pending(doc).lease, original)
    with pytest.raises(HTTPException):
        jobs.commit(identity)
    assert state._sessions[doc].design is None
    assert owner.read_pending(doc).payload == original.payload


def test_worker_metadata_cannot_substitute_batch_scope(immediate, monkeypatch):
    doc, owner = immediate
    original, _ = store(immediate)
    native = transport.evaluate_payload

    def changed(payload):
        report = native(payload)
        assert report['result']['status'] == 'verified'
        report['metadata']['scope_tag'] = 'registered_batch_v1'
        return report

    monkeypatch.setattr(transport, 'evaluate_payload', changed)
    identity, job = start()
    assert job.result['status'] != 'ready' and job.candidate is None
    with pytest.raises(HTTPException):
        jobs.commit(identity)
    assert state._sessions[doc].design is None
    assert owner.read_pending(doc).payload == original.payload


def test_nonreproducible_saved_geometry_stays_pending_and_unpublished(immediate):
    from backend.api.part_immutable_revision import prepare_geometry_revision
    doc, owner = immediate
    source, _, _ = prepared()
    source.feature_log[0].params['length_bp'] += 1
    broken = prepare_geometry_revision(source)
    owner.cache.write(owner.reserve_empty(doc), broken)
    identity, job = start()
    assert job.result['status'] != 'ready' and job.candidate is None
    with pytest.raises(HTTPException):
        jobs.commit(identity)
    assert state._sessions[doc].design is None
    assert owner.read_pending(doc).payload == broken.payload


def test_gate_change_during_worker_prevents_completion_handoff(immediate, monkeypatch):
    doc, owner = immediate
    original, _ = store(immediate)
    native = transport.evaluate_payload

    def disable(payload):
        report = native(payload)
        monkeypatch.setattr(authority, 'ENABLED', False)
        return report

    monkeypatch.setattr(transport, 'evaluate_payload', disable)
    identity, job = start()
    assert job.result['status'] != 'ready' and job.candidate is None
    with pytest.raises(HTTPException):
        jobs.commit(identity)
    assert state._sessions[doc].design is None
    assert owner.read_pending(doc).payload == original.payload


def test_geometry_wire_context_is_explicit_and_rejects_version_scope_mixing(immediate, monkeypatch):
    import json
    store(immediate)
    original = transport.encode_input
    observed = []

    def encode(ticket):
        parts, binding = original(ticket)
        context = json.loads(parts[-1])
        assert context['version'] == 2 and context['storage_scope'] == 'native_extrusion_v1'
        for changed in ({**context, 'version': 1},
                        {**context, 'storage_scope': 'registered_batch_v1'},
                        {key: value for key, value in context.items() if key != 'storage_scope'}):
            with pytest.raises(ValueError):
                transport._context(changed)
        observed.append(context)
        return parts, binding

    monkeypatch.setattr(transport, 'encode_input', encode)
    identity, job = start()
    assert job.result['status'] == 'ready' and observed
    jobs.commit(identity)
